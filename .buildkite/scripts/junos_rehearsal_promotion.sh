#!/usr/bin/env bash
# TEMPORARY JUNOS-001 PR REHEARSAL — delete before merge.
set -euo pipefail
umask 077

if [[ "${BUILDKITE_STEP_KEY:-}" != rehearsal-promotion || \
  "${BUILDKITE_AGENT_META_DATA_QUEUE:-}" != ncdp-validation ]]; then
  echo "Buildkite rehearsal promotion step or queue is invalid" >&2
  exit 2
fi
if [[ "${BUILDKITE_RETRY_COUNT:-0}" != 0 ]]; then
  echo "retried rehearsal promotion is not authorized" >&2
  exit 2
fi
if [[ -z "${BUILDKITE_PULL_REQUEST:-}" || \
  "${BUILDKITE_PULL_REQUEST}" == false ]]; then
  echo "rehearsal promotion requires a pull request build" >&2
  exit 2
fi

scripts/buildkite/verify_staging_commit.sh
tmpdir="$(mktemp -d)"
compose=(
  docker compose
  --project-name "ncdp-junos-rehearsal-promotion-${BUILDKITE_BUILD_NUMBER}"
  -f compose.assurance.yaml
)
export NCDP_PROMOTION_IMAGE_TAG="rehearsal-${BUILDKITE_BUILD_NUMBER}"
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
"${promotion_run[@]}" ncdp assure-plan \
  --plan deployments/live/promotion/plan.json \
  --policy deployments/live/promotion/policy.yaml \
  --baseline deployments/live/promotion/baseline \
  --report-json /output/assurance.json \
  --batfish
promotion="$tmpdir/promotion"
"${promotion_run[@]}" ncdp promote \
  --plan deployments/live/promotion/plan.json \
  --policy deployments/live/promotion/policy.yaml \
  --baseline deployments/live/promotion/baseline \
  --assurance /output/assurance.json \
  --git-commit "$BUILDKITE_COMMIT" \
  --output /output/promotion
"${promotion_run[@]}" ncdp verify-promotion \
  --promotion /output/promotion \
  --git-commit "$BUILDKITE_COMMIT"
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
buildkite-agent meta-data set \
  "promoted-assurance-digest" "$promoted_assurance_digest"
buildkite-agent meta-data set \
  "promoted-promotion-digest" "$promoted_promotion_digest"
echo "Junos rehearsal promotion bound to exact PR commit"
