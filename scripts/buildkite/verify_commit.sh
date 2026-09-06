#!/usr/bin/env bash
set -euo pipefail

: "${BUILDKITE_BRANCH:?BUILDKITE_BRANCH is required}"
: "${BUILDKITE_COMMIT:?BUILDKITE_COMMIT is required}"
pr_assurance=0
if [[ "${BUILDKITE_STEP_KEY:-}" == cml-staging ]]; then
  # Staging binds the exact queued PR or main commit, including an older main
  # build serialized behind another staging run. It never grants delivery.
  pr_assurance=1
elif [[ "${BUILDKITE_STEP_KEY:-}" == pr-batfish-assurance ]]; then
  case "${BUILDKITE_REPO:-}" in
    https://github.com/Atheer-Kareem/network-change-delivery-platform.git|git@github.com:Atheer-Kareem/network-change-delivery-platform.git) ;;
    *) echo "non-canonical Batfish repository rejected" >&2; exit 2 ;;
  esac
  if [[ "${BUILDKITE_PULL_REQUEST:-}" =~ ^[1-9][0-9]*$ ]]; then
    if [[ "${BUILDKITE_PULL_REQUEST_REPO:-}" != "${BUILDKITE_REPO}" ]]; then
      echo "fork-origin or ambiguous Batfish PR rejected" >&2
      exit 2
    fi
  elif [[ "${BUILDKITE_SOURCE:-}" != ui || "${BUILDKITE_BRANCH}" != main || \
    "${BUILDKITE_PULL_REQUEST:-}" != false || \
    "${NCDP_DEMO_CONTINUE_ON_FAILURE:-}" != 1 || \
    -n "${BUILDKITE_PULL_REQUEST_REPO:-}" || \
    -n "${BUILDKITE_PULL_REQUEST_BASE_BRANCH:-}" || \
    -n "${BUILDKITE_TRIGGERED_FROM_BUILD_ID:-}" || -n "${BUILDKITE_TAG:-}" ]]; then
    echo "Batfish requires a canonical PR or explicit manual-main demo" >&2
    exit 2
  fi
  pr_assurance=1
elif [[ "$BUILDKITE_BRANCH" != main || \
  -n "${BUILDKITE_PULL_REQUEST:-}" && "${BUILDKITE_PULL_REQUEST}" != "false" ]]; then
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
if (( pr_assurance == 0 )); then
  git fetch --no-tags origin main
  if [[ "$(git rev-parse origin/main)" != "$BUILDKITE_COMMIT" ]]; then
    echo "origin/main does not match Buildkite commit" >&2
    exit 2
  fi
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
