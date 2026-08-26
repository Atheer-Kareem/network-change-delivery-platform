#!/usr/bin/env bash
set -euo pipefail

[[ "${BUILDKITE_STEP_KEY:-}" == deploy-gate ]]
[[ "${BUILDKITE_AGENT_META_DATA_QUEUE:-}" == ncdp-deploy ]]
retry_count="${BUILDKITE_RETRY_COUNT:-0}"
if [[ "$retry_count" != 0 ]]; then
  echo "retried deployment job is not authorized" >&2
  exit 2
fi
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
buildkite-agent artifact download \
  "staging-evidence/staging-run.json" "$tmpdir" --step cml-staging
staging_evidence="$tmpdir/staging-evidence/staging-run.json"
[[ -f "$staging_evidence" && ! -L "$staging_evidence" ]]
promoted_plan_digest="$(buildkite-agent meta-data get "promoted-plan-digest")"
promoted_assurance_digest="$(buildkite-agent meta-data get "promoted-assurance-digest")"
promoted_promotion_digest="$(buildkite-agent meta-data get "promoted-promotion-digest")"
uv run ncdp verify-buildkite-gate \
  --promotion "$promotion" \
  --promoted-plan-digest "$promoted_plan_digest" \
  --promoted-assurance-digest "$promoted_assurance_digest" \
  --promoted-promotion-digest "$promoted_promotion_digest"
uv run ncdp audit verify-buildkite \
  --promotion "$promotion" \
  --staging-evidence "$staging_evidence"
if uv run ncdp buildkite-live-request-status; then
  :
else
  request_status=$?
  [[ "$request_status" -eq 3 ]]
  uv run ncdp audit persist-buildkite \
    --promotion "$promotion" \
    --staging-evidence "$staging_evidence"
  echo "device write executed: NO"
  exit 0
fi
uv run ncdp verify-buildkite-live-request --promotion "$promotion"
uv run ncdp verify-deployment-ansible-runtime
report_relative="deployment-evidence/change-record.json"
report="$tmpdir/$report_relative"
set +e
buildkite-agent oidc request-token \
  --audience urn:ncdp:openbao:deploy \
  --lifetime 300 \
  --subject-claim pipeline_id |
  uv run ncdp deploy-buildkite-promotion \
    --promotion "$promotion" \
    --report-json "$report"
deployment_status=$?
set -e
upload_status=1
if [[ -f "$report" && ! -L "$report" ]]; then
  set +e
  (
    cd "$tmpdir"
    buildkite-agent artifact upload "$report_relative"
  )
  upload_status=$?
  set -e
fi
audit_status=1
if [[ -f "$report" && ! -L "$report" ]]; then
  set +e
  uv run ncdp audit persist-buildkite \
    --promotion "$promotion" \
    --staging-evidence "$staging_evidence" \
    --change-record "$report"
  audit_status=$?
  set -e
fi
if [[ "$deployment_status" -ne 0 ]]; then
  if [[ -f "$report" && ! -L "$report" ]]; then
    echo "deployment failed; inspect the uploaded typed ChangeRecord evidence"
    if [[ "$audit_status" -ne 0 ]]; then
      echo "durable audit persistence also failed; deployment outcome remains primary"
    fi
  else
    echo "deployment failed before typed ChangeRecord evidence was produced"
  fi
  exit "$deployment_status"
fi
if [[ ! -f "$report" || -L "$report" ]]; then
  echo "deployment completed without required typed ChangeRecord evidence"
  exit 1
fi
if [[ "$audit_status" -ne 0 ]]; then
  echo "device outcome occurred, but durable audit persistence failed" >&2
  echo "deployment will not be retried or recovered for an audit-only failure" >&2
  exit 1
fi
if [[ "$upload_status" -ne 0 ]]; then
  echo "typed ChangeRecord upload failed after durable audit persistence" >&2
  exit "$upload_status"
fi
echo "device write executed: YES"
