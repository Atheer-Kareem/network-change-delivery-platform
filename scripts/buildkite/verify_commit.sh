#!/usr/bin/env bash
set -euo pipefail

: "${BUILDKITE_BRANCH:?BUILDKITE_BRANCH is required}"
: "${BUILDKITE_COMMIT:?BUILDKITE_COMMIT is required}"
if [[ "$BUILDKITE_BRANCH" != main || -n "${BUILDKITE_PULL_REQUEST:-}" && "${BUILDKITE_PULL_REQUEST}" != "false" ]]; then
  echo "commit binding requires a non-PR main build" >&2
  exit 2
fi
if [[ ! "$BUILDKITE_COMMIT" =~ ^[0-9a-f]{40}$ ]]; then
  echo "invalid Buildkite commit" >&2
  exit 2
fi
[[ "$(git rev-parse HEAD)" == "$BUILDKITE_COMMIT" ]]
git fetch --no-tags origin main
[[ "$(git rev-parse origin/main)" == "$BUILDKITE_COMMIT" ]]
git diff --quiet "$BUILDKITE_COMMIT" --
echo "commit binding verified: $BUILDKITE_COMMIT"
