#!/usr/bin/env bash
set -euo pipefail

[[ "${BUILDKITE_STEP_KEY:-}" == deploy-gate ]]
[[ "${BUILDKITE_AGENT_META_DATA_QUEUE:-}" == ncdp-deploy ]]
scripts/buildkite/verify_commit.sh
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
