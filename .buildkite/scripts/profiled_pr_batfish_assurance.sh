#!/usr/bin/env bash
set -euo pipefail
umask 077

if [[ "${BUILDKITE_STEP_KEY:-}" != pr-batfish-assurance ]]; then
  echo "Profiled PR Batfish assurance execution context is not authorized" >&2
  exit 2
fi
if [[ "${BUILDKITE_AGENT_META_DATA_QUEUE:-}" != ncdp-validation ]]; then
  echo "Profiled PR Batfish assurance queue is not authorized" >&2
  exit 2
fi
if [[ "${BUILDKITE_RETRY_COUNT:-}" != 0 ]]; then
  echo "Retried profiled PR Batfish assurance is not authorized" >&2
  exit 2
fi

scripts/buildkite/verify_commit.sh
tmpdir="$(mktemp -d)"
chmod 700 "$tmpdir"
mkdir -m 700 "$tmpdir/assurance"
compose=(
  docker compose
  --project-name ncdp-profiled-pr-batfish-assurance
  -f compose.assurance.yaml
)
export NCDP_PROMOTION_IMAGE_TAG="$BUILDKITE_BUILD_NUMBER"
cleanup() {
  cleanup_primary_status=$?
  trap - EXIT
  cleanup_status=0
  if ! "${compose[@]}" down >/dev/null 2>&1; then
    echo "Profiled PR Batfish cleanup failed: Compose teardown did not complete" >&2
    cleanup_status=3
  fi
  if ! rm -rf "$tmpdir" >/dev/null 2>&1; then
    echo "Profiled PR Batfish cleanup failed: temporary removal did not complete" >&2
    cleanup_status=3
  fi
  if (( cleanup_primary_status != 0 )); then
    exit "$cleanup_primary_status"
  fi
  exit "$cleanup_status"
}
trap cleanup EXIT

"${compose[@]}" down --remove-orphans >/dev/null 2>&1 || true
"${compose[@]}" build promotion
"${compose[@]}" up -d batfish
assurance_run=(
  "${compose[@]}" run --rm --no-deps
  --user "$(id -u):$(id -g)"
  --volume "$tmpdir:/output"
  promotion
)

ready_deadline=$((SECONDS + 60))
until "${assurance_run[@]}" python scripts/buildkite/batfish_ready.py; do
  if (( SECONDS >= ready_deadline )); then
    echo "Profiled PR Batfish readiness timed out" >&2
    exit 2
  fi
  sleep 2
done

evidence_relative="assurance/profiled-pr-assurance.json"
evidence="$tmpdir/$evidence_relative"
summary="$tmpdir/assurance/summary.md"
set +e
"${assurance_run[@]}" python \
  scripts/assurance/verify_profiled_pr_candidate.py \
  --evidence "/output/$evidence_relative"
assurance_status=$?
set -e

render_summary() {
  [[ -d "$tmpdir/assurance" && ! -L "$tmpdir/assurance" ]] || return 2
  [[ -f "$evidence" && ! -L "$evidence" ]] || return 2
  "${assurance_run[@]}" python \
    scripts/buildkite/render_profiled_pr_assurance_annotation.py \
    --evidence "/output/$evidence_relative" > "$summary" || return 2
}

publish_evidence() {
  local style="$1"
  render_summary || return 2
  (
    cd "$tmpdir"
    buildkite-agent artifact upload "$evidence_relative"
  ) || return 2
  cat "$summary" || return 2
  buildkite-agent annotate \
    --style "$style" \
    --context batfish-assurance < "$summary" || return 2
}

if (( assurance_status != 0 )); then
  set +e
  publish_evidence error
  publication_status=$?
  set -e
  if (( publication_status != 0 )); then
    echo "Safe profiled PR assurance publication did not complete" >&2
  fi
  exit "$assurance_status"
fi

[[ -f "$evidence" && ! -L "$evidence" ]]
"${assurance_run[@]}" python \
  scripts/assurance/verify_profiled_pr_candidate.py \
  --evidence "/output/$evidence_relative" \
  --verify-only
publish_evidence success
echo "Profiled PR Batfish artifact published: $evidence_relative"
