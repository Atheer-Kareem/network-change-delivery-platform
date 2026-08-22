#!/usr/bin/env bash
set -euo pipefail
scripts/buildkite/verify_commit.sh
tmpdir="$(mktemp -d)"
trap 'docker compose -f compose.assurance.yaml down >/dev/null 2>&1 || true; rm -rf "$tmpdir"' EXIT
docker compose -f compose.assurance.yaml down --remove-orphans >/dev/null 2>&1 || true
docker compose -f compose.assurance.yaml up -d batfish
ready_deadline=$((SECONDS + 60))
until UV_CACHE_DIR=/tmp/ncdp-uv-cache uv run python scripts/buildkite/batfish_ready.py; do
  if (( SECONDS >= ready_deadline )); then
    echo "Batfish readiness timed out" >&2
    exit 2
  fi
  sleep 2
done
uv run ncdp assure-plan --plan fixtures/batfish/plans/fleet-interface-description.json --policy fixtures/batfish/policy.yaml --baseline fixtures/batfish/baseline --report-json "$tmpdir/assurance.json" --batfish
promotion="$tmpdir/promotion"
uv run ncdp promote --plan fixtures/batfish/plans/fleet-interface-description.json --policy fixtures/batfish/policy.yaml --baseline fixtures/batfish/baseline --assurance "$tmpdir/assurance.json" --git-commit "$BUILDKITE_COMMIT" --output "$promotion"
uv run ncdp verify-promotion --promotion "$promotion" --git-commit "$BUILDKITE_COMMIT"
(
  cd "$tmpdir"
  buildkite-agent artifact upload 'promotion/**'
)
