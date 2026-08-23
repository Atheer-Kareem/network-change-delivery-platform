#!/usr/bin/env bash
set -euo pipefail
scripts/buildkite/verify_commit.sh
tmpdir="$(mktemp -d)"
compose=(docker compose --project-name ncdp-promotion -f compose.assurance.yaml)
export NCDP_PROMOTION_IMAGE_TAG="$BUILDKITE_BUILD_NUMBER"
trap '"${compose[@]}" down >/dev/null 2>&1 || true; rm -rf "$tmpdir"' EXIT
"${compose[@]}" down --remove-orphans >/dev/null 2>&1 || true
"${compose[@]}" build promotion
"${compose[@]}" up -d batfish
promotion_run=(
  "${compose[@]}" run --rm --no-deps
  --user "$(id -u):$(id -g)"
  --volume "$tmpdir:/output"
  promotion
)
ready_deadline=$((SECONDS + 60))
until "${promotion_run[@]}" python scripts/buildkite/batfish_ready.py; do
  if (( SECONDS >= ready_deadline )); then
    echo "Batfish readiness timed out" >&2
    exit 2
  fi
  sleep 2
done
"${promotion_run[@]}" ncdp assure-plan --plan fixtures/batfish/plans/fleet-interface-description.json --policy fixtures/batfish/policy.yaml --baseline fixtures/batfish/baseline --report-json /output/assurance.json --batfish
promotion="$tmpdir/promotion"
"${promotion_run[@]}" ncdp promote --plan fixtures/batfish/plans/fleet-interface-description.json --policy fixtures/batfish/policy.yaml --baseline fixtures/batfish/baseline --assurance /output/assurance.json --git-commit "$BUILDKITE_COMMIT" --output /output/promotion
"${promotion_run[@]}" ncdp verify-promotion --promotion /output/promotion --git-commit "$BUILDKITE_COMMIT"
[[ -f "$promotion/manifest.json" ]]
(
  cd "$tmpdir"
  buildkite-agent artifact upload 'promotion/**'
)
promoted_plan_digest="$(
  "${promotion_run[@]}" ncdp promotion-digest \
    --promotion /output/promotion \
    --git-commit "$BUILDKITE_COMMIT" \
    --field plan
)"
promoted_assurance_digest="$(
  "${promotion_run[@]}" ncdp promotion-digest \
    --promotion /output/promotion \
    --git-commit "$BUILDKITE_COMMIT" \
    --field assurance
)"
promoted_promotion_digest="$(
  "${promotion_run[@]}" ncdp promotion-digest \
    --promotion /output/promotion \
    --git-commit "$BUILDKITE_COMMIT" \
    --field promotion
)"
buildkite-agent meta-data set "promoted-plan-digest" "$promoted_plan_digest"
buildkite-agent meta-data set "promoted-assurance-digest" "$promoted_assurance_digest"
buildkite-agent meta-data set "promoted-promotion-digest" "$promoted_promotion_digest"
