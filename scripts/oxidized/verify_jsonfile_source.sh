#!/bin/sh
set -eu

source_file=${1:?private router.json path required}
image=${2:-ncdp-oxidized:10c2}
name="ncdp-oxidized-jsonfile-$$"
fixture=$(mktemp -d "${TMPDIR:-/tmp}/ncdp-oxidized-jsonfile.XXXXXX")
container=

cleanup() {
  if [ -n "${container}" ]; then
    docker rm --force "${container}" >/dev/null 2>&1 || true
  fi
  rm -rf "${fixture}"
}
trap cleanup EXIT HUP INT TERM

python3 - "${source_file}" <<'PY' || {
import os
import stat
import sys

metadata = os.lstat(sys.argv[1])
valid = (
    stat.S_ISREG(metadata.st_mode)
    and not stat.S_ISLNK(metadata.st_mode)
    and metadata.st_uid == os.getuid()
    and stat.S_IMODE(metadata.st_mode) == 0o600
    and metadata.st_nlink == 1
)
raise SystemExit(0 if valid else 1)
PY
  echo "private Oxidized source rejected" >&2
  exit 1
}
mkdir "${fixture}/configs"
cat > "${fixture}/config" <<EOF
---
interval: 0
use_syslog: false
threads: 1
rest: 0.0.0.0:8888
source:
  default: jsonfile
  jsonfile:
    file: /run/ncdp/router.json
    map:
      name: name
      ip: ip
      model: model
      group: group
      username: username
      password: password
    vars_map:
      ssh_port: ssh_port
output:
  default: file
  file:
    directory: /home/oxidized/.config/oxidized/configs
EOF

container=$(docker run --detach \
  --name "${name}" \
  --read-only \
  --cap-drop ALL \
  --security-opt no-new-privileges \
  --tmpfs /tmp:rw,noexec,nosuid,nodev,size=16m \
  --mount "type=bind,source=${fixture},target=/home/oxidized/.config/oxidized" \
  --mount "type=bind,source=${source_file},target=/run/ncdp/router.json,readonly" \
  --publish 127.0.0.1::8888 \
  "${image}")

binding=$(docker inspect --format '{{(index (index .NetworkSettings.Ports "8888/tcp") 0).HostIp}}' "${container}")
[ "${binding}" = "127.0.0.1" ] || exit 1
port=$(docker inspect --format '{{(index (index .NetworkSettings.Ports "8888/tcp") 0).HostPort}}' "${container}")

attempt=0
response=
while [ "${attempt}" -lt 30 ]; do
  if [ "$(docker inspect --format '{{.State.Running}}' "${container}")" != true ]; then
    echo "Oxidized JSONFile container exited before readiness" >&2
    exit 1
  fi
  if response=$(curl --silent --fail --max-time 2 \
    "http://127.0.0.1:${port}/nodes.json" 2>/dev/null); then
    break
  fi
  attempt=$((attempt + 1))
  sleep 1
done
[ -n "${response}" ] || exit 1
printf '%s' "${response}" | jq -e '
  length == 4
  and ([.[].name] | sort) == ["netbox-device-1", "netbox-device-2", "netbox-device-8", "netbox-device-9"]
  and ([.[].model] | sort) == ["IOS", "IOS", "IOS", "JunOS"]
  and all(.[]; .status == "never" and .last == null)
  and all(.[]; (has("config") or has("diff")) | not)
' >/dev/null
[ -z "$(find "${fixture}/configs" -type f -print -quit)" ] || exit 1
echo "Oxidized JSONFile compatibility: PASS (4 nodes, status never)"
