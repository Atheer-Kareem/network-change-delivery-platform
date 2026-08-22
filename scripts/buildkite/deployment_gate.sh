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
plan_digest="$(python -c 'import json,sys; print(json.load(open(sys.argv[1]))["plan_digest"])' "$promotion/manifest.json")"
assurance_digest="$(python -c 'import json,sys; print(json.load(open(sys.argv[1]))["assurance_record_digest"])' "$promotion/manifest.json")"
promotion_digest="$(python -c 'import json,sys; print(json.load(open(sys.argv[1]))["digest"])' "$promotion/manifest.json")"
[[ "${BUILDKITE_APPROVED_PLAN_DIGEST:-}" == "$plan_digest" ]]
[[ "${BUILDKITE_APPROVED_ASSURANCE_DIGEST:-}" == "$assurance_digest" ]]
[[ "${BUILDKITE_APPROVED_PROMOTION_DIGEST:-}" == "$promotion_digest" ]]
ncdp verify-promotion --promotion "$promotion" --git-commit "$BUILDKITE_COMMIT"
printf 'commit: %s\nplan digest: %s\nassurance digest: %s\npromotion digest: %s\ndeployment authorization gate: PASSED\ndevice write executed: NO\n' "$BUILDKITE_COMMIT" "$plan_digest" "$assurance_digest" "$promotion_digest"
