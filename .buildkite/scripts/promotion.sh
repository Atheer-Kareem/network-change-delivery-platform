#!/usr/bin/env bash
set -euo pipefail
umask 077

scripts/buildkite/verify_commit.sh
tmpdir="$(mktemp -d)"
chmod 700 "$tmpdir"
cleanup() {
  cleanup_primary_status=$?
  trap - EXIT
  cleanup_status=0
  if ! rm -rf "$tmpdir" >/dev/null 2>&1; then
    echo "Promotion cleanup failed: temporary directory removal did not complete" >&2
    cleanup_status=3
  fi
  if (( cleanup_primary_status != 0 )); then
    exit "$cleanup_primary_status"
  fi
  exit "$cleanup_status"
}
trap cleanup EXIT
assert_artifact_tree_count() {
  local expected="$1"
  local observed
  if ! observed="$(find "$tmpdir" -print | wc -l | tr -d '[:space:]')"; then
    echo "Assurance artifact tree inspection failed" >&2
    return 2
  fi
  if [[ "$observed" != "$expected" ]]; then
    echo "Assurance artifact tree has an unexpected filesystem shape" >&2
    return 2
  fi
}
[[ -d "$tmpdir" && ! -L "$tmpdir" ]]
assert_artifact_tree_count 1
image="ncdp-promotion:$BUILDKITE_BUILD_NUMBER"
docker build --target promotion --tag "$image" .

(
  cd "$tmpdir"
  buildkite-agent artifact download \
    "assurance/assurance.json" . \
    --step batfish-assurance \
    --build "$BUILDKITE_BUILD_ID"
)
assurance_directory="$tmpdir/assurance"
assurance="$assurance_directory/assurance.json"
[[ -d "$tmpdir" && ! -L "$tmpdir" ]]
[[ -d "$assurance_directory" && ! -L "$assurance_directory" ]]
[[ -f "$assurance" && ! -L "$assurance" ]]
assert_artifact_tree_count 3

promotion_run=(
  docker run --rm
  --user "$(id -u):$(id -g)"
  --volume "$tmpdir:/output"
  "$image"
)
"${promotion_run[@]}" ncdp verify-assurance \
  --plan deployments/live/promotion/plan.json \
  --policy deployments/live/promotion/policy.yaml \
  --baseline deployments/live/promotion/baseline \
  --evidence /output/assurance/assurance.json
promotion="$tmpdir/promotion"
"${promotion_run[@]}" ncdp promote \
  --plan deployments/live/promotion/plan.json \
  --policy deployments/live/promotion/policy.yaml \
  --baseline deployments/live/promotion/baseline \
  --assurance /output/assurance/assurance.json \
  --git-commit "$BUILDKITE_COMMIT" \
  --output /output/promotion
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
