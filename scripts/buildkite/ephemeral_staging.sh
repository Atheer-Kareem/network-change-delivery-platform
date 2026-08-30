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
run_id="bk-${BUILDKITE_BUILD_ID}"
run_directory="${NCDP_STAGING_STATE_ROOT}/ephemeral/${run_id}"
evidence_relative="staging-evidence/staging-run.json"
mkdir -p staging-evidence

set +e
buildkite-agent oidc request-token \
  --audience urn:ncdp:openbao:staging \
  --lifetime 300 \
  --subject-claim pipeline_id \
  --claim build_id |
  uv run python scripts/run_ephemeral_cml_staging.py \
    --identity buildkite \
    --run-id "$run_id" \
    --run-directory "$run_directory" \
    --evidence "$evidence_relative"
staging_status=$?
set -e

rendered_summary=""
render_summary() {
  [[ -f "$evidence_relative" && ! -L "$evidence_relative" ]] || return 2
  rendered_summary="$(
    uv run --frozen python scripts/buildkite/render_staging_annotation.py \
      --evidence "$evidence_relative"
  )" || return 2
}

publish_evidence() {
  local style="$1"
  render_summary || return 2
  buildkite-agent artifact upload "$evidence_relative" || return 2
  printf '%s\n' "$rendered_summary" || return 2
  printf '%s\n' "$rendered_summary" |
    buildkite-agent annotate \
      --style "$style" \
      --context cml-staging || return 2
}

if [[ "$staging_status" -ne 0 ]]; then
  set +e
  publish_evidence error
  publication_status=$?
  set -e
  if [[ "$publication_status" -ne 0 ]]; then
    echo "staging failed; safe evidence publication did not complete" >&2
  fi
  exit "$staging_status"
fi
if [[ ! -f "$evidence_relative" || -L "$evidence_relative" ]]; then
  echo "staging completed without required sanitized evidence" >&2
  exit 1
fi
publish_evidence success
echo "Ephemeral CML staging evidence published: $evidence_relative"
