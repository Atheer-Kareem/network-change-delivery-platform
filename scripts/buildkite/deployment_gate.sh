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
approved_plan_digest="$(buildkite-agent meta-data get "approved-plan-digest")"
approved_assurance_digest="$(buildkite-agent meta-data get "approved-assurance-digest")"
approved_promotion_digest="$(buildkite-agent meta-data get "approved-promotion-digest")"
uv run ncdp verify-buildkite-gate \
  --promotion "$promotion" \
  --approved-plan-digest "$approved_plan_digest" \
  --approved-assurance-digest "$approved_assurance_digest" \
  --approved-promotion-digest "$approved_promotion_digest"
