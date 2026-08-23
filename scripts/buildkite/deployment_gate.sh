#!/usr/bin/env bash
set -euo pipefail

[[ "${BUILDKITE_STEP_KEY:-}" == deploy-gate ]]
[[ "${BUILDKITE_AGENT_META_DATA_QUEUE:-}" == ncdp-deploy ]]
scripts/buildkite/verify_commit.sh
for prohibited_variable in \
  NCDP_OPENBAO_ROLE_ID \
  NCDP_OPENBAO_SECRET_ID \
  NCDP_DEVICE_USERNAME \
  NCDP_DEVICE_PASSWORD; do
  if [[ -n "${!prohibited_variable:-}" ]]; then
    echo "prohibited deployment credential is present: $prohibited_variable" >&2
    exit 2
  fi
done
buildkite-agent oidc request-token \
  --audience urn:ncdp:openbao:deploy \
  --lifetime 300 \
  --subject-claim pipeline_id |
  uv run ncdp verify-buildkite-openbao-identity
if [[ "${NCDP_OPENBAO_JWT_DIAGNOSTICS:-}" == 1 ]]; then
  echo "OpenBao JWT diagnostic completed; promotion and deployment remain stopped"
  exit 0
fi
tmpdir="$(mktemp -d)"
trap 'rm -rf "$tmpdir"' EXIT
buildkite-agent artifact download "promotion/**" "$tmpdir" --step promotion
promotion="$tmpdir/promotion"
[[ -f "$promotion/manifest.json" ]]
promoted_plan_digest="$(buildkite-agent meta-data get "promoted-plan-digest")"
promoted_assurance_digest="$(buildkite-agent meta-data get "promoted-assurance-digest")"
promoted_promotion_digest="$(buildkite-agent meta-data get "promoted-promotion-digest")"
uv run ncdp verify-buildkite-gate \
  --promotion "$promotion" \
  --promoted-plan-digest "$promoted_plan_digest" \
  --promoted-assurance-digest "$promoted_assurance_digest" \
  --promoted-promotion-digest "$promoted_promotion_digest"
if uv run ncdp buildkite-live-request-status; then
  :
else
  request_status=$?
  [[ "$request_status" -eq 3 ]]
  exit 0
fi
uv run ncdp verify-buildkite-live-request --promotion "$promotion"
report_relative="deployment-evidence/change-record.json"
report="$tmpdir/$report_relative"
buildkite-agent oidc request-token \
  --audience urn:ncdp:openbao:deploy \
  --lifetime 300 \
  --subject-claim pipeline_id |
  uv run ncdp deploy-buildkite-promotion \
    --promotion "$promotion" \
    --report-json "$report"
(
  cd "$tmpdir"
  buildkite-agent artifact upload "$report_relative"
)
echo "device write executed: YES"
