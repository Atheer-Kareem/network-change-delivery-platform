#!/usr/bin/env bash
# Install outside the checkout as the agent-owned ncdp-staging command hook.
set +x
set -euo pipefail
umask 077

if [[ "${BUILDKITE_STEP_KEY:-}" != cml-staging || \
  "${BUILDKITE_AGENT_META_DATA_QUEUE:-}" != ncdp-staging || \
  "${BUILDKITE_RETRY_COUNT:-}" != 0 || \
  "${BUILDKITE_COMMAND:-}" != .buildkite/scripts/profiled_cml_staging.sh ]]; then
  echo "non-staging command is not authorized on the staging agent" >&2
  exit 2
fi

case "${BUILDKITE_REPO:-}" in
  https://github.com/Atheer-Kareem/network-change-delivery-platform.git|git@github.com:Atheer-Kareem/network-change-delivery-platform.git) ;;
  *) echo "non-canonical staging repository rejected" >&2; exit 2 ;;
esac
if [[ "${BUILDKITE_PULL_REQUEST:-}" != false ]]; then
  if [[ ! "${BUILDKITE_PULL_REQUEST:-}" =~ ^[1-9][0-9]*$ || \
    "${BUILDKITE_PULL_REQUEST_REPO:-}" != "${BUILDKITE_REPO}" ]]; then
    echo "fork-origin or ambiguous staging PR rejected" >&2
    exit 2
  fi
elif [[ "${BUILDKITE_BRANCH:-}" != main ]]; then
  echo "non-PR staging requires main" >&2
  exit 2
fi

for prohibited_variable in \
  NCDP_OPENBAO_ROLE_ID NCDP_OPENBAO_SECRET_ID NCDP_NETBOX_TOKEN \
  CML2_TOKEN NCDP_DEVICE_USERNAME NCDP_DEVICE_PASSWORD; do
  if [[ -n "${!prohibited_variable:-}" ]]; then
    echo "ambient staging authority rejected" >&2
    exit 2
  fi
done

# Resolve the protected file beside this installed hook, never through HOME or
# a checkout-provided path. Repository pre-command hooks have already finished.
staging_environment="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)/staging.env"
if [[ ! -f "$staging_environment" || -L "$staging_environment" || \
  ! -O "$staging_environment" ]]; then
  echo "protected staging environment is unavailable" >&2
  exit 2
fi
staging_environment_mode="$(
  stat -c '%a' "$staging_environment" 2>/dev/null ||
    stat -f '%Lp' "$staging_environment" 2>/dev/null
)" || { echo "protected staging environment mode unavailable" >&2; exit 2; }
if [[ "$staging_environment_mode" != 600 ]]; then
  echo "protected staging environment must have mode 0600" >&2
  exit 2
fi
# The expected identity must come from the protected file, never an inherited
# checkout/job environment value. Preserve the actual job identity across source.
readonly staging_pipeline_id="${BUILDKITE_PIPELINE_ID:-}"
unset NCDP_BUILDKITE_PIPELINE_ID
set -a
source "$staging_environment"
set +a
if [[ -z "$staging_pipeline_id" || -z "${NCDP_BUILDKITE_PIPELINE_ID:-}" || \
  "$staging_pipeline_id" != "$NCDP_BUILDKITE_PIPELINE_ID" ]]; then
  echo "Buildkite staging pipeline identity rejected" >&2
  exit 2
fi
exec .buildkite/scripts/profiled_cml_staging.sh
