#!/usr/bin/env bash
set -euo pipefail
umask 077

if [[ "${BUILDKITE_STEP_KEY:-}" != cml-staging || \
  "${BUILDKITE_AGENT_META_DATA_QUEUE:-}" != ncdp-staging ]]; then
  echo "Buildkite staging step or queue is invalid" >&2
  exit 2
fi
if [[ "${BUILDKITE_RETRY_COUNT:-0}" != 0 ]]; then
  echo "retried staging job is not authorized" >&2
  exit 2
fi
if [[ "${BUILDKITE_BRANCH:-}" != main || \
  "${BUILDKITE_PULL_REQUEST:-false}" != false ]]; then
  echo "credentialed staging requires reviewed merged main" >&2
  exit 2
fi
scripts/buildkite/verify_staging_commit.sh
for prohibited_variable in \
  NCDP_OPENBAO_ROLE_ID \
  NCDP_OPENBAO_SECRET_ID \
  NCDP_NETBOX_TOKEN \
  CML2_TOKEN \
  NCDP_DEVICE_USERNAME \
  NCDP_DEVICE_PASSWORD; do
  if [[ -n "${!prohibited_variable:-}" ]]; then
    echo "prohibited staging credential is present: $prohibited_variable" >&2
    exit 2
  fi
done

if [[ -z "${NCDP_STAGING_STATE_ROOT:-}" || -z "${BUILDKITE_BUILD_ID:-}" ]]; then
  echo "Buildkite staging state root or build identity is missing" >&2
  exit 2
fi
evidence_relative="staging-evidence/staging-run.json"
mkdir -p staging-evidence

set +e
buildkite-agent oidc request-token \
  --audience urn:ncdp:openbao:staging \
  --lifetime 300 \
  --subject-claim pipeline_id \
  --claim build_id |
  uv run ncdp-staging-controller \
    --evidence "$evidence_relative"
staging_status=$?
set -e

if [[ -f "$evidence_relative" && ! -L "$evidence_relative" ]]; then
  buildkite-agent artifact upload "$evidence_relative"
fi
if [[ "$staging_status" -ne 0 ]]; then
  if [[ -f "$evidence_relative" && ! -L "$evidence_relative" ]]; then
    echo "staging failed; inspect the sanitized staging evidence artifact"
  else
    echo "staging failed before sanitized evidence was produced"
  fi
  exit "$staging_status"
fi
if [[ ! -f "$evidence_relative" || -L "$evidence_relative" ]]; then
  echo "staging completed without required sanitized evidence" >&2
  exit 1
fi
