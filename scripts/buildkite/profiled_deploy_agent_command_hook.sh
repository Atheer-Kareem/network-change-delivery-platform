#!/usr/bin/env bash
# Reviewed source; install as the agent-owned ncdp-deploy command hook.
set +x
set -euo pipefail
umask 077
deny() { echo "NO WRITE — profiled agent admission rejected" >&2; exit 2; }

[[ "${BUILDKITE_BRANCH:-}" == main && "${BUILDKITE_PULL_REQUEST:-}" == false && \
   -z "${BUILDKITE_PULL_REQUEST_REPO:-}" && \
   "${BUILDKITE_AGENT_META_DATA_QUEUE:-}" == ncdp-deploy && \
   "${BUILDKITE_RETRY_COUNT:-}" == 0 && \
   "${BUILDKITE_COMMAND:-}" == .buildkite/scripts/profiled_delivery.sh ]] || deny
case "${BUILDKITE_STEP_KEY:-}" in profiled-live-plan|profiled-rollout-live-plan|profiled-deploy|profiled-rollout-deploy) ;; *) deny ;; esac
case "${BUILDKITE_REPO:-}" in
  https://github.com/Atheer-Kareem/network-change-delivery-platform.git|git@github.com:Atheer-Kareem/network-change-delivery-platform.git) ;;
  *) deny ;;
esac
[[ "${BUILDKITE_COMMIT:-}" =~ ^[0-9a-f]{40}$ ]] || deny
[[ "$(git rev-parse HEAD)" == "$BUILDKITE_COMMIT" ]] || deny
git diff --quiet "$BUILDKITE_COMMIT" -- || deny
[[ -z "$(git ls-files --others --exclude-standard)" ]] || deny

for variable in NCDP_NETBOX_TOKEN NCDP_OPENBAO_ROLE_ID NCDP_OPENBAO_SECRET_ID \
  NCDP_AUDIT_STORE_ROOT CML2_TOKEN NCDP_DEVICE_USERNAME NCDP_DEVICE_PASSWORD; do
  [[ -z "${!variable:-}" ]] || deny
done
hook_directory="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
mode_of() { stat -c '%a' "$1" 2>/dev/null || stat -f '%Lp' "$1" 2>/dev/null; }
[[ -d "$hook_directory" && -O "$hook_directory" && "$(mode_of "$hook_directory")" == 700 ]] || deny
protected="$hook_directory/profiled.env"
[[ -f "$protected" && ! -L "$protected" && -O "$protected" && \
   "$(mode_of "$protected")" == 600 ]] || deny
readonly job_pipeline="${BUILDKITE_PIPELINE_ID:-}"
unset NCDP_BUILDKITE_PIPELINE_ID
set -a
source "$protected"
set +a
[[ -n "$job_pipeline" && "$job_pipeline" == "${NCDP_BUILDKITE_PIPELINE_ID:-}" ]] || deny
for variable in NCDP_NETBOX_URL NCDP_NETBOX_TOKEN NCDP_OPENBAO_URL \
  NCDP_OPENBAO_ROLE_ID NCDP_OPENBAO_SECRET_ID NCDP_PROFILED_DELIVERY_STATE_ROOT; do
  [[ -n "${!variable:-}" ]] || deny
done
if [[ "$BUILDKITE_STEP_KEY" == profiled-deploy || "$BUILDKITE_STEP_KEY" == profiled-rollout-deploy ]]; then
  [[ -n "${NCDP_AUDIT_STORE_ROOT:-}" && "$NCDP_AUDIT_STORE_ROOT" == /* && \
     -d "$NCDP_AUDIT_STORE_ROOT" && ! -L "$NCDP_AUDIT_STORE_ROOT" && \
     -O "$NCDP_AUDIT_STORE_ROOT" && "$(mode_of "$NCDP_AUDIT_STORE_ROOT")" == 700 ]] || deny
  audit_resolved="$(cd -- "$NCDP_AUDIT_STORE_ROOT" && pwd -P)"
  [[ "$audit_resolved" == "$NCDP_AUDIT_STORE_ROOT" ]] || deny
  checkout="$(pwd -P)"
  [[ "$audit_resolved" != "$checkout" && "$audit_resolved" != "$checkout/"* ]] || deny
fi
# Repository pre-command hooks have already finished; only this command receives authority.
exec .buildkite/scripts/profiled_delivery.sh
