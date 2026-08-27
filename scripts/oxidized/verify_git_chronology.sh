#!/bin/sh
set -eu

image=${1:-ncdp-oxidized:10c2}
fixture=$(mktemp -d "${TMPDIR:-/tmp}/ncdp-oxidized-git.XXXXXX")
history="${fixture}/config-history.git"
evidence="${fixture}/results.json"
archive="${fixture}/chronology.tar"

cleanup() {
  rm -rf "${fixture}"
}
trap cleanup EXIT HUP INT TERM
chmod 0700 "${fixture}"

docker run --rm \
  --network none \
  --read-only \
  --cap-drop ALL \
  --security-opt no-new-privileges \
  --env HOME=/run/ncdp/home \
  --tmpfs /tmp:rw,noexec,nosuid,nodev,size=16m \
  --tmpfs /run/ncdp:rw,noexec,nosuid,nodev,mode=0700,uid=30000,gid=30000,size=32m \
  --mount "type=bind,source=$(pwd)/scripts/oxidized/git_chronology_harness.rb,target=/harness.rb,readonly" \
  --entrypoint /bin/sh \
  "${image}" -ec '
    bundle _2.5.22_ exec ruby /harness.rb /run/ncdp/config-history.git > /run/ncdp/results.json
    tar -C /run/ncdp -cf - config-history.git results.json
  ' > "${archive}"

tar -C "${fixture}" -xf "${archive}"
rm "${archive}"
chmod 0700 "${history}"

UV_CACHE_DIR=${UV_CACHE_DIR:-/tmp/ncdp-uv-cache} \
  uv run python scripts/oxidized/verify_git_chronology.py "${history}" "${evidence}"

persistent=/Users/netdevops/.local/state/ncdp/oxidized/config-history.git
if [ -e "${persistent}" ]; then
  [ "$(/usr/bin/git --git-dir="${persistent}" rev-parse --is-bare-repository)" = true ]
  [ "$(/usr/bin/git --git-dir="${persistent}" rev-list --all --count)" -eq 0 ]
  [ -z "$(/usr/bin/git --git-dir="${persistent}" config --local --name-only --get-regexp '^remote\.' 2>/dev/null || true)" ]
  [ ! -e "${persistent}/objects/info/alternates" ]
  [ ! -e "${persistent}/refs/replace" ]
fi
