#!/bin/sh
set -eu

image=${1:-ncdp-oxidized:10c2}
runtime_name="ncdp-oxidized-10c2-$$"
fixture_root=$(mktemp -d "${TMPDIR:-/tmp}/ncdp-oxidized-10c2.XXXXXX")
container_id=

cleanup() {
  if [ -n "${container_id}" ]; then
    docker rm --force "${container_id}" >/dev/null 2>&1 || true
  fi
  rm -rf "${fixture_root}"
}
trap cleanup EXIT HUP INT TERM

mkdir -p "${fixture_root}/configs"
printf '%s\n' '192.0.2.1:ios' > "${fixture_root}/router.db"
cat > "${fixture_root}/config" <<EOF
---
interval: 0
use_syslog: false
debug: false
threads: 1
timeout: 2
retries: 0
rest: 0.0.0.0:8888
source:
  default: csv
  csv:
    file: /home/oxidized/.config/oxidized/router.db
    delimiter: !ruby/regexp /:/
    map:
      name: 0
      model: 1
output:
  default: file
  file:
    directory: /home/oxidized/.config/oxidized/configs
EOF

container_id=$(docker run --detach \
  --name "${runtime_name}" \
  --read-only \
  --cap-drop ALL \
  --security-opt no-new-privileges \
  --tmpfs /tmp:rw,noexec,nosuid,nodev,size=16m \
  --mount "type=bind,source=${fixture_root},target=/home/oxidized/.config/oxidized" \
  --publish 127.0.0.1::8888 \
  "${image}")

host_binding=$(docker inspect --format '{{(index (index .NetworkSettings.Ports "8888/tcp") 0).HostIp}}' "${container_id}")
[ "${host_binding}" = "127.0.0.1" ] || {
  echo "synthetic Oxidized API was not published on IPv4 loopback" >&2
  exit 1
}
host_port=$(docker inspect --format '{{(index (index .NetworkSettings.Ports "8888/tcp") 0).HostPort}}' "${container_id}")

ready=0
attempt=0
while [ "${attempt}" -lt 30 ]; do
  if [ "$(docker inspect --format '{{.State.Running}}' "${container_id}")" != "true" ]; then
    echo "synthetic Oxidized container exited before readiness" >&2
    docker logs "${container_id}" >&2 || true
    exit 1
  fi
  if response=$(curl --silent --show-error --fail --max-time 2 \
    "http://127.0.0.1:${host_port}/nodes.json" 2>/dev/null); then
    ready=1
    break
  fi
  attempt=$((attempt + 1))
  sleep 1
done
[ "${ready}" -eq 1 ] || {
  echo "synthetic Oxidized API readiness timeout" >&2
  docker logs "${container_id}" >&2 || true
  exit 1
}
printf '%s' "${response}" | jq -e '
  length == 1
  and .[0].name == "192.0.2.1"
  and .[0].model == "IOS"
  and .[0].status == "never"
  and .[0].last == null
  and (.[0] | has("config") | not)
  and (.[0] | has("diff") | not)
' >/dev/null || {
  echo "synthetic Oxidized API returned unexpected node metadata" >&2
  exit 1
}
[ -z "$(find "${fixture_root}/configs" -type f -print -quit)" ] || {
  echo "synthetic Oxidized runtime produced configuration output" >&2
  exit 1
}

docker inspect "${container_id}" | jq -e '
  .[0]
  | .Config.User == "30000:30000"
    and .HostConfig.Privileged == false
    and .HostConfig.NetworkMode != "host"
    and (.HostConfig.Binds // [] | all(contains("docker.sock") | not))
    and (.Mounts | all(.Source | contains("network-change-delivery-platform") | not))
    and (.Config.Env | all(
      startswith("NCDP_OPENBAO_") or
      startswith("NCDP_NETBOX_") or
      startswith("BAO_TOKEN=") or
      startswith("VAULT_TOKEN=")
      | not
    ))
' >/dev/null

[ "$(docker exec "${container_id}" id -u)" -ne 0 ]
echo "Oxidized synthetic runtime acceptance: PASS"
echo "API route: /nodes.json"
echo "Synthetic nodes: 1"
echo "Configuration outputs: 0"
