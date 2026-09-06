#!/usr/bin/env bash
set +x
set -euo pipefail
umask 077

if [[ "${BUILDKITE_STEP_KEY:-}" != cml-staging || \
  "${BUILDKITE_AGENT_META_DATA_QUEUE:-}" != ncdp-staging || \
  "${BUILDKITE_RETRY_COUNT:-}" != 0 ]]; then
  echo "Buildkite staging context rejected" >&2
  exit 2
fi

exec uv run --frozen python scripts/buildkite/run_profiled_cml_staging.py
