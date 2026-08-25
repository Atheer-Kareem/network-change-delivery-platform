#!/usr/bin/env bash
set -euo pipefail

if [[ "${BUILDKITE_STEP_KEY:-}" != cml-staging || \
  "${BUILDKITE_AGENT_META_DATA_QUEUE:-}" != ncdp-staging || \
  "${BUILDKITE_COMMAND:-}" != scripts/buildkite/ephemeral_staging.sh ]]; then
  echo "non-staging command is not authorized on the staging agent" >&2
  exit 2
fi

if [[ -n "${BUILDKITE_PULL_REQUEST_REPO:-}" && \
  "${BUILDKITE_PULL_REQUEST_REPO}" != "${BUILDKITE_REPO:-}" ]]; then
  echo "fork-origin staging jobs are not authorized" >&2
  exit 2
fi

staging_environment="${HOME:?}/.config/buildkite/ncdp-lab/hooks/ncdp-staging/staging.env"
if [[ ! -f "$staging_environment" || -L "$staging_environment" ]]; then
  echo "protected staging environment is unavailable" >&2
  exit 2
fi
# The agent-owned file is loaded only after the job boundary is accepted and
# repository pre-command hooks have completed.
source "$staging_environment"
exec scripts/buildkite/ephemeral_staging.sh
