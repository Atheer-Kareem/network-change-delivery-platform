#!/usr/bin/env bash
set -euo pipefail

treeish="${1:-HEAD}"
image_tag="permission-test"
image="ncdp-promotion:$image_tag"
context="$(mktemp -d)"
output="$(mktemp -d)"
compose=(
  docker compose
  --project-name ncdp-promotion-permission-test
  -f compose.assurance.yaml
)
cleanup() {
  "${compose[@]}" down >/dev/null 2>&1 || true
  rm -rf "$context" "$output"
}
trap cleanup EXIT

git archive "$treeish" | (umask 077; tar -x -C "$context")
docker build --no-cache --target promotion --tag "$image" "$context"

docker run --rm --user 65532:65532 "$image" python -c '
import os
from pathlib import Path
import network_change_delivery

immutable_directories = (
    Path(".venv"),
    Path("src/network_change_delivery"),
    Path("fixtures/batfish"),
    Path("scripts/buildkite"),
)
for path in immutable_directories:
    assert os.access(path, os.R_OK | os.X_OK)
    assert not os.access(path, os.W_OK)

required = (
    Path("scripts/buildkite/batfish_ready.py"),
    Path("scripts/buildkite/render_assurance_annotation.py"),
    Path("fixtures/batfish/plans/fleet-interface-description.json"),
    Path("fixtures/batfish/policy.yaml"),
    Path("fixtures/batfish/baseline/configs/core-02.cfg"),
)
for path in required:
    path.read_bytes()
'
docker run --rm --user 65532:65532 "$image" ncdp --version

export NCDP_PROMOTION_IMAGE_TAG="$image_tag"
"${compose[@]}" down --remove-orphans >/dev/null 2>&1 || true
"${compose[@]}" up -d batfish
promotion_run=(
  "${compose[@]}" run --rm --no-deps
  --user "$(id -u):$(id -g)"
  --volume "$output:/output"
  promotion
)
ready=0
for _ in {1..30}; do
  if "${promotion_run[@]}" python scripts/buildkite/batfish_ready.py; then
    ready=1
    break
  fi
  sleep 2
done
[[ "$ready" == 1 ]]

"${promotion_run[@]}" ncdp assure-plan \
  --plan fixtures/batfish/plans/fleet-interface-description.json \
  --policy fixtures/batfish/policy.yaml \
  --baseline fixtures/batfish/baseline \
  --report-json /output/assurance.json \
  --batfish
"${promotion_run[@]}" ncdp promote \
  --plan fixtures/batfish/plans/fleet-interface-description.json \
  --policy fixtures/batfish/policy.yaml \
  --baseline fixtures/batfish/baseline \
  --assurance /output/assurance.json \
  --git-commit 0000000000000000000000000000000000000000 \
  --output /output/promotion
"${promotion_run[@]}" ncdp verify-promotion \
  --promotion /output/promotion \
  --git-commit 0000000000000000000000000000000000000000

[[ -f "$output/promotion/manifest.json" ]]
[[ "$(stat -f '%Lp' "$output/promotion")" == 700 ]]
[[ "$(stat -f '%Lp' "$output/promotion/manifest.json")" == 600 ]]
echo "restrictive-context promotion smoke: PASSED"
