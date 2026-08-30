#!/usr/bin/env bash
# TEMPORARY JUNOS-001 PR REHEARSAL — restore protected-main version before merge.
set -euo pipefail
umask 077

if [[ "${BUILDKITE_STEP_KEY:-}" != cml-staging || \
  "${BUILDKITE_AGENT_META_DATA_QUEUE:-}" != ncdp-staging ]]; then
  echo "Buildkite rehearsal staging step or queue is invalid" >&2
  exit 2
fi
if [[ "${BUILDKITE_RETRY_COUNT:-0}" != 0 ]]; then
  echo "retried rehearsal job is not authorized" >&2
  exit 2
fi
if [[ -z "${BUILDKITE_PULL_REQUEST:-}" || \
  "${BUILDKITE_PULL_REQUEST}" == false ]]; then
  echo "Junos rehearsal requires a pull request build" >&2
  exit 2
fi
scripts/buildkite/verify_staging_commit.sh
for prohibited_variable in \
  NCDP_OPENBAO_ROLE_ID \
  NCDP_OPENBAO_SECRET_ID \
  NCDP_NETBOX_TOKEN \
  CML2_TOKEN \
  NCDP_DEVICE_USERNAME \
  NCDP_DEVICE_PASSWORD \
  NCDP_AUDIT_PREWRITE_VERIFIED \
  NCDP_AUDIT_STORE_ROOT; do
  if [[ -n "${!prohibited_variable:-}" ]]; then
    echo "prohibited rehearsal credential or authority is present" >&2
    exit 2
  fi
done
if [[ -z "${NCDP_STAGING_STATE_ROOT:-}" || -z "${BUILDKITE_BUILD_ID:-}" ]]; then
  echo "Buildkite staging state root or build identity is missing" >&2
  exit 2
fi

run_id="bk-${BUILDKITE_BUILD_ID}"
run_directory="${NCDP_STAGING_STATE_ROOT}/ephemeral/${run_id}"
evidence_relative="rehearsal-evidence/junos-snmp.json"
tmpdir="$(mktemp -d)"
cleanup() {
  rm -rf "$tmpdir"
  rm -rf rehearsal-evidence
}
trap cleanup EXIT
if [[ -e rehearsal-evidence || -L rehearsal-evidence ]]; then
  echo "rehearsal evidence path already exists" >&2
  exit 2
fi
mkdir -m 700 rehearsal-evidence

buildkite-agent artifact download 'promotion/**' "$tmpdir" \
  --step rehearsal-promotion
promotion="$tmpdir/promotion"
[[ -f "$promotion/manifest.json" ]]
uv run ncdp verify-promotion \
  --promotion "$promotion" \
  --git-commit "$BUILDKITE_COMMIT"

promoted_plan_digest="$(buildkite-agent meta-data get promoted-plan-digest)"
promoted_assurance_digest="$(
  buildkite-agent meta-data get promoted-assurance-digest
)"
promoted_promotion_digest="$(
  buildkite-agent meta-data get promoted-promotion-digest
)"
[[ "$(uv run ncdp promotion-digest \
  --promotion "$promotion" \
  --git-commit "$BUILDKITE_COMMIT" \
  --field plan)" == "$promoted_plan_digest" ]]
[[ "$(uv run ncdp promotion-digest \
  --promotion "$promotion" \
  --git-commit "$BUILDKITE_COMMIT" \
  --field assurance)" == "$promoted_assurance_digest" ]]
[[ "$(uv run ncdp promotion-digest \
  --promotion "$promotion" \
  --git-commit "$BUILDKITE_COMMIT" \
  --field promotion)" == "$promoted_promotion_digest" ]]

set +e
buildkite-agent oidc request-token \
  --audience urn:ncdp:openbao:staging \
  --lifetime 300 \
  --subject-claim pipeline_id \
  --claim build_id |
  uv run python -m scripts.run_junos_snmp_rehearsal \
    --run-id "$run_id" \
    --run-directory "$run_directory" \
    --promotion "$promotion" \
    --promoted-plan-digest "$promoted_plan_digest" \
    --promoted-assurance-digest "$promoted_assurance_digest" \
    --promoted-promotion-digest "$promoted_promotion_digest" \
    --evidence "$evidence_relative"
rehearsal_status=$?
set -e

if [[ -f "$evidence_relative" && ! -L "$evidence_relative" ]]; then
  buildkite-agent artifact upload "$evidence_relative"
fi
if [[ "$rehearsal_status" -ne 0 ]]; then
  if [[ -f "$evidence_relative" && ! -L "$evidence_relative" ]]; then
    echo "rehearsal failed; inspect the sanitized evidence artifact"
  else
    echo "rehearsal failed before sanitized evidence was produced"
  fi
  exit "$rehearsal_status"
fi
if [[ ! -f "$evidence_relative" || -L "$evidence_relative" ]]; then
  echo "rehearsal completed without required sanitized evidence" >&2
  exit 1
fi
echo "Junos SNMP disposable-CML rehearsal: SUCCEEDED"
