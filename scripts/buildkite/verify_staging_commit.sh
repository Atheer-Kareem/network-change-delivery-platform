#!/usr/bin/env bash
set -euo pipefail

: "${BUILDKITE_COMMIT:?BUILDKITE_COMMIT is required}"
if [[ ! "$BUILDKITE_COMMIT" =~ ^[0-9a-f]{40}$ ]]; then
  echo "invalid Buildkite staging commit" >&2
  exit 2
fi
if [[ "$(git rev-parse HEAD)" != "$BUILDKITE_COMMIT" ]]; then
  echo "staging checkout does not match Buildkite commit" >&2
  exit 2
fi
if ! git diff --quiet "$BUILDKITE_COMMIT" --; then
  echo "tracked staging checkout content differs" >&2
  exit 2
fi
if [[ -n "$(git ls-files --others --exclude-standard)" ]]; then
  echo "non-ignored untracked staging files present" >&2
  exit 2
fi
echo "staging commit binding verified: $BUILDKITE_COMMIT"
