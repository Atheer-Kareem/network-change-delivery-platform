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
if [[ "$(git rev-parse HEAD)" != "$BUILDKITE_COMMIT" ]]; then
  echo "checkout does not match Buildkite commit" >&2
  exit 2
fi
git fetch --no-tags origin main
if [[ "$(git rev-parse origin/main)" != "$BUILDKITE_COMMIT" ]]; then
  echo "origin/main does not match Buildkite commit" >&2
  exit 2
fi
if ! git diff --quiet "$BUILDKITE_COMMIT" --; then
  echo "tracked checkout content differs" >&2
  exit 2
fi
if [[ -n "$(git ls-files --others --exclude-standard)" ]]; then
  echo "non-ignored untracked files present" >&2
  exit 2
fi
echo "commit binding verified: $BUILDKITE_COMMIT"
