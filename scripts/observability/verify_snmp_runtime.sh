#!/bin/bash
set -euo pipefail

root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
quality_image=${NCDP_QUALITY_IMAGE:?NCDP_QUALITY_IMAGE required}
run_id=${BUILDKITE_BUILD_NUMBER:-$$}
project="ncdp-snmpv3-synthetic-test-${run_id}"
telemetry_network="${project}-telemetry"
snmp_control_network="${project}-snmp-control"
snmp_device_network="${project}-snmp-device"
exporter_image='prom/snmp-exporter:v0.30.1@sha256:e5fd5e8b43ace6c088fe9bf0b37b7fff0e04380bee352be7ec41b853a4dd5859'
prometheus_image='prom/prometheus:v3.14.0@sha256:5ce7540c3c00ef4ab0c9d2c995c6a5b9c421f44b4a115d97a2c7af3b1c21cbb0'
agent_image="ncdp-snmp-agent:${run_id}"
uid=$(id -u)
gid=$(id -g)
[ "${uid}" -gt 0 ] && [ "${gid}" -gt 0 ]

test_root=$(mktemp -d)
config_root=${test_root}/config
runtime_root=${test_root}/runtime
state_root=${test_root}/state
module_root=${test_root}/modules
auth_root=${test_root}/auth
agent_1_root=${test_root}/agent-1
agent_2_root=${test_root}/agent-2
# These two agents are a minimum disposable SNMPv3 protocol fixture. They do
# not select, model, or limit the managed fleet; live SNMP migration remains a
# separate profiled exact-four concern.
evidence_root=${test_root}/evidence
prometheus_port=$((29090 + run_id % 100))
grafana_port=$((23000 + run_id % 100))
export NCDP_OBSERVABILITY_UID=${uid}
export NCDP_OBSERVABILITY_GID=${gid}
export NCDP_OBSERVABILITY_CONFIG_ROOT=${config_root}
export NCDP_OBSERVABILITY_STATE_ROOT=${state_root}
export NCDP_OBSERVABILITY_RUNTIME_ROOT=${runtime_root}
export NCDP_OBSERVABILITY_NETWORK=${telemetry_network}
export NCDP_SNMP_CONTROL_NETWORK=${snmp_control_network}
export NCDP_SNMP_DEVICE_NETWORK=${snmp_device_network}
export NCDP_SNMP_MODULE_ROOT=${module_root}
export NCDP_SNMP_AUTH_ROOT=${auth_root}
export NCDP_PROMETHEUS_CONTAINER="${project}-prometheus"
export NCDP_BLACKBOX_CONTAINER="${project}-blackbox"
export NCDP_GRAFANA_CONTAINER="${project}-grafana"
export NCDP_ALERTMANAGER_CONTAINER="${project}-alertmanager"
export NCDP_RECEIVER_CONTAINER="${project}-receiver"
export NCDP_SNMP_EXPORTER_CONTAINER="${project}-snmp-exporter"
export NCDP_PROMETHEUS_PORT=${prometheus_port}
export NCDP_GRAFANA_PORT=${grafana_port}

compose=(
  docker compose --project-name "${project}"
  --file "${root}/infrastructure/observability/compose.yaml"
  --file "${root}/infrastructure/observability/compose-snmp.yaml"
)

cleanup() {
  docker rm -f "${project}-agent-1" "${project}-agent-2" >/dev/null 2>&1 || true
  "${compose[@]}" down --volumes --remove-orphans >/dev/null 2>&1 || true
  rm -rf "${test_root}"
}
trap cleanup EXIT

quality_python() {
  docker run --rm --user "${uid}:${gid}" \
    -v "${test_root}:/test-root" \
    "${quality_image}" /app/.venv/bin/python "$@"
}

private_get() {
  local url=$1
  local output=$2
  docker run --rm --network "${snmp_control_network}" "${quality_image}" \
    /app/.venv/bin/python -c '
import sys, urllib.request
with urllib.request.urlopen(sys.argv[1], timeout=20) as response:
    sys.stdout.buffer.write(response.read())
' "${url}" >"${output}"
}

private_status() {
  local method=$1
  local url=$2
  docker run --rm --network "${snmp_control_network}" "${quality_image}" \
    /app/.venv/bin/python -c '
import sys, urllib.error, urllib.request
request = urllib.request.Request(sys.argv[2], method=sys.argv[1])
try:
    with urllib.request.urlopen(request, timeout=25) as response:
        print(response.status)
except urllib.error.HTTPError as error:
    print(error.code)
except (TimeoutError, urllib.error.URLError):
    print(599)
' "${method}" "${url}"
}

write_agent_config() {
  local directory=$1
  local username_a=$2
  local auth_a=$3
  local privacy_a=$4
  local username_b=$5
  local auth_b=$6
  local privacy_b=$7
  mkdir -p "${directory}"
  chmod 0700 "${directory}"
  {
    printf 'createUser %s SHA256 "%s" AES "%s"\n' \
      "${username_a}" "${auth_a}" "${privacy_a}"
    printf 'createUser %s SHA256 "%s" AES "%s"\n' \
      "${username_b}" "${auth_b}" "${privacy_b}"
  } >"${directory}/agent-users.conf"
  {
    printf 'agentAddress udp:1161\n'
    for oid in \
      .1.3.6.1.2.1.1.3 .1.3.6.1.2.1.2.1 .1.3.6.1.2.1.2.2.1.1 \
      .1.3.6.1.2.1.2.2.1.7 .1.3.6.1.2.1.2.2.1.8 \
      .1.3.6.1.2.1.2.2.1.13 .1.3.6.1.2.1.2.2.1.14 \
      .1.3.6.1.2.1.2.2.1.19 .1.3.6.1.2.1.2.2.1.20 \
      .1.3.6.1.2.1.31.1.1.1.1 .1.3.6.1.2.1.31.1.1.1.6 \
      .1.3.6.1.2.1.31.1.1.1.10 .1.3.6.1.2.1.31.1.1.1.15 \
      .1.3.6.1.2.1.31.1.1.1.19 .1.3.6.1.2.1.31.1.5; do
      printf 'view ncdp included %s\n' "${oid}"
    done
    printf 'rouser %s priv -V ncdp\n' "${username_a}"
    printf 'rouser %s priv -V ncdp\n' "${username_b}"
  } >"${directory}/snmpd.conf"
  {
    printf 'mibs :\n'
    printf 'defVersion 3\n'
    printf 'defSecurityLevel authPriv\n'
    printf 'defSecurityName %s\n' "${username_a}"
    printf 'defAuthType SHA-256\n'
    printf 'defAuthPassphrase %s\n' "${auth_a}"
    printf 'defPrivType AES\n'
    printf 'defPrivPassphrase %s\n' "${privacy_a}"
  } >"${directory}/snmp.conf"
  chmod 0600 "${directory}/agent-users.conf" "${directory}/snmpd.conf"
  chmod 0600 "${directory}/snmp.conf"
}

write_auth_a() {
  local auth_output=$1
  {
    printf 'auths:\n'
    printf '  ncdp_device_1_a:\n    version: 3\n    security_level: authPriv\n    username: %s\n    password: %s\n    auth_protocol: SHA256\n    priv_protocol: AES\n    priv_password: %s\n' "${username_1_a}" "${auth_1_a}" "${privacy_1_a}"
    printf '  ncdp_device_2_a:\n    version: 3\n    security_level: authPriv\n    username: %s\n    password: %s\n    auth_protocol: SHA256\n    priv_protocol: AES\n    priv_password: %s\n' "${username_2_a}" "${auth_2_a}" "${privacy_2_a}"
    printf '  ncdp_wrong_auth:\n    version: 3\n    security_level: authPriv\n    username: %s\n    password: %s\n    auth_protocol: SHA256\n    priv_protocol: AES\n    priv_password: %s\n' "${username_1_a}" "${wrong_auth}" "${privacy_1_a}"
    printf '  ncdp_wrong_privacy:\n    version: 3\n    security_level: authPriv\n    username: %s\n    password: %s\n    auth_protocol: SHA256\n    priv_protocol: AES\n    priv_password: %s\n' "${username_1_a}" "${auth_1_a}" "${wrong_privacy}"
  } >"${auth_output}"
  chmod 0600 "${auth_output}"
}

write_auth_b() {
  local auth_output=$1
  {
    printf 'auths:\n'
    printf '  ncdp_device_1_b:\n    version: 3\n    security_level: authPriv\n    username: %s\n    password: %s\n    auth_protocol: SHA256\n    priv_protocol: AES\n    priv_password: %s\n' "${username_1_b}" "${auth_1_b}" "${privacy_1_b}"
    printf '  ncdp_device_2_b:\n    version: 3\n    security_level: authPriv\n    username: %s\n    password: %s\n    auth_protocol: SHA256\n    priv_protocol: AES\n    priv_password: %s\n' "${username_2_b}" "${auth_2_b}" "${privacy_2_b}"
  } >"${auth_output}"
  chmod 0600 "${auth_output}"
}

# Preserve the accepted five-service runtime through its existing unchanged gate.
if [ "${NCDP_SKIP_OBSERVABILITY_REGRESSION:-0}" != 1 ]; then
  NCDP_QUALITY_IMAGE="${quality_image}" "${root}/scripts/observability/verify_runtime.sh"
fi

mkdir -p "${config_root}" "${runtime_root}/rules" \
  "${runtime_root}/alertmanager" "${runtime_root}/grafana/provisioning/datasources" \
  "${runtime_root}/grafana/provisioning/dashboards" \
  "${runtime_root}/grafana/dashboards" "${runtime_root}/receiver" \
  "${state_root}/discovery" "${state_root}/runtime" "${state_root}/control" \
  "${state_root}/prometheus" "${state_root}/grafana" \
  "${state_root}/alertmanager" "${module_root}" "${auth_root}" "${evidence_root}"
find "${test_root}" -type d -exec chmod 0700 {} +
cp "${root}/infrastructure/observability/blackbox.yml" "${config_root}/blackbox.yml"
cp "${root}/infrastructure/observability/rules/management-reachability-alerts.yml" "${runtime_root}/rules/management-reachability-alerts.yml"
cp "${root}/infrastructure/observability/alertmanager.yml" "${runtime_root}/alertmanager/alertmanager.yml"
cp "${root}/infrastructure/observability/grafana/provisioning/datasources/prometheus.yml" "${runtime_root}/grafana/provisioning/datasources/prometheus.yml"
cp "${root}/infrastructure/observability/grafana/provisioning/dashboards/dashboards.yml" "${runtime_root}/grafana/provisioning/dashboards/dashboards.yml"
cp "${root}/infrastructure/observability/grafana/dashboards/ncdp-management-reachability.json" "${runtime_root}/grafana/dashboards/ncdp-management-reachability.json"
cp "${root}/scripts/observability/demo_receiver.py" "${runtime_root}/receiver/demo_receiver.py"
cp "${root}/infrastructure/observability/snmp/snmp-modules.yml" "${module_root}/snmp-modules.yml"
find "${test_root}" -type f -exec chmod 0600 {} +

username_1_a="u1a$(openssl rand -hex 8)"
auth_1_a="a1a$(openssl rand -hex 16)"
privacy_1_a="p1a$(openssl rand -hex 16)"
username_2_a="u2a$(openssl rand -hex 8)"
auth_2_a="a2a$(openssl rand -hex 16)"
privacy_2_a="p2a$(openssl rand -hex 16)"
username_1_b="u1b$(openssl rand -hex 8)"
auth_1_b="a1b$(openssl rand -hex 16)"
privacy_1_b="p1b$(openssl rand -hex 16)"
username_2_b="u2b$(openssl rand -hex 8)"
auth_2_b="a2b$(openssl rand -hex 16)"
privacy_2_b="p2b$(openssl rand -hex 16)"
wrong_auth="wrongauth$(openssl rand -hex 16)"
wrong_privacy="wrongpriv$(openssl rand -hex 16)"
sentinels=(
  "${username_1_a}" "${auth_1_a}" "${privacy_1_a}"
  "${username_2_a}" "${auth_2_a}" "${privacy_2_a}"
  "${username_1_b}" "${auth_1_b}" "${privacy_1_b}"
  "${username_2_b}" "${auth_2_b}" "${privacy_2_b}"
  "${wrong_auth}" "${wrong_privacy}"
)
sentinel_labels=(
  username-1-a auth-1-a privacy-1-a
  username-2-a auth-2-a privacy-2-a
  username-1-b auth-1-b privacy-1-b
  username-2-b auth-2-b privacy-2-b
  wrong-auth wrong-privacy
)
write_agent_config "${agent_1_root}" \
  "${username_1_a}" "${auth_1_a}" "${privacy_1_a}" \
  "${username_1_b}" "${auth_1_b}" "${privacy_1_b}"
write_agent_config "${agent_2_root}" \
  "${username_2_a}" "${auth_2_a}" "${privacy_2_a}" \
  "${username_2_b}" "${auth_2_b}" "${privacy_2_b}"
write_auth_a "${test_root}/auth-a.yml"

quality_python /app/scripts/observability/prepare_snmp_synthetic.py publish-auth \
  --directory /test-root/auth --source /test-root/auth-a.yml
quality_python /app/scripts/observability/prepare_snmp_synthetic.py prepare \
  --base-prometheus /app/infrastructure/observability/prometheus.yml \
  --prometheus-output /test-root/config/prometheus.yml \
  --state-root /test-root/state --generation a

docker pull --platform linux/arm64 "${exporter_image}" >/dev/null
exporter_details=$(docker image inspect "${exporter_image}" --format '{{.Id}} {{.Os}}/{{.Architecture}}')
read -r exporter_image_id exporter_platform <<<"${exporter_details}"
[ "${exporter_platform}" = linux/arm64 ]
docker build --platform linux/arm64 --tag "${agent_image}" \
  "${root}/infrastructure/observability/snmp/synthetic-agent" >/dev/null
agent_details=$(docker image inspect "${agent_image}" --format '{{.Id}} {{.Os}}/{{.Architecture}}')
read -r agent_image_id agent_platform <<<"${agent_details}"
[ "${agent_platform}" = linux/arm64 ]

docker run --rm --platform linux/arm64 --read-only --cap-drop ALL \
  --security-opt no-new-privileges --user "${uid}:${gid}" \
  -v "${config_root}/prometheus.yml:/etc/ncdp/prometheus.yml:ro" \
  -v "${runtime_root}/rules:/etc/ncdp/rules:ro" \
  --entrypoint /bin/promtool "${prometheus_image}" \
  check config /etc/ncdp/prometheus.yml >/dev/null

"${compose[@]}" config >"${evidence_root}/compose-rendered.yml"
"${compose[@]}" create snmp_exporter >/dev/null
for index in 1 2; do
  directory_var="agent_${index}_root"
  directory=${!directory_var}
  docker run --detach --name "${project}-agent-${index}" \
    --network "${snmp_device_network}" \
    --network-alias "synthetic-snmp-agent-${index}" \
    --read-only --cap-drop ALL --security-opt no-new-privileges \
    --tmpfs /var/lib/snmp:rw,noexec,nosuid,nodev,size=8m \
    --volume "${directory}:/run/ncdp-agent:ro" \
    "${agent_image}" >/dev/null
done

# Prove the disposable agent's SHA256/AES128/authPriv configuration independently
# before using exporter behavior as pipeline evidence. Credentials remain in the
# private client configuration file and never enter arguments or environment.
for index in 1 2; do
  directory_var="agent_${index}_root"
  directory=${!directory_var}
  docker run --rm --network "${snmp_device_network}" --read-only --cap-drop ALL \
    --security-opt no-new-privileges \
    --env SNMPCONFPATH=/run/ncdp-client \
    --volume "${directory}:/run/ncdp-client:ro" \
    --entrypoint /usr/bin/snmpget "${agent_image}" \
    -Oqv "udp:synthetic-snmp-agent-${index}:1161" .1.3.6.1.2.1.1.3.0 \
    >"${evidence_root}/agent-${index}-authpriv.txt"
done
"${compose[@]}" up --detach --pull never --no-build >/dev/null

topology_file=${evidence_root}/network-topology.json
network_file=${evidence_root}/network-definitions.json
docker inspect \
  "${NCDP_PROMETHEUS_CONTAINER}" "${NCDP_SNMP_EXPORTER_CONTAINER}" \
  "${project}-agent-1" "${project}-agent-2" >"${topology_file}"
docker network inspect "${snmp_control_network}" "${snmp_device_network}" \
  >"${network_file}"
quality_python -c '
import json, sys
from pathlib import Path

containers = {
    item["Name"].lstrip("/"): item
    for item in json.loads(Path(sys.argv[1]).read_text())
}
networks = {
    item["Name"]: item
    for item in json.loads(Path(sys.argv[2]).read_text())
}
telemetry, control, device, project = sys.argv[3:]
prometheus = f"{project}-prometheus"
exporter = f"{project}-snmp-exporter"
agent_1 = f"{project}-agent-1"
agent_2 = f"{project}-agent-2"

def attached(name):
    return set(containers[name]["NetworkSettings"]["Networks"])

assert attached(prometheus) == {telemetry, control}
assert attached(exporter) == {control, device}
assert attached(agent_1) == {device}
assert attached(agent_2) == {device}
assert networks[control]["Internal"] is True
assert networks[device]["Internal"] is False
control_members = {item["Name"] for item in networks[control]["Containers"].values()}
device_members = {item["Name"] for item in networks[device]["Containers"].values()}
assert control_members == {prometheus, exporter}
assert device_members == {exporter, agent_1, agent_2}
' /test-root/evidence/network-topology.json \
  /test-root/evidence/network-definitions.json "${telemetry_network}" \
  "${snmp_control_network}" "${snmp_device_network}" "${project}"

for _ in $(seq 1 60); do
  if private_get "http://snmp_exporter:9116/-/healthy" \
    "${evidence_root}/exporter-health" 2>/dev/null && \
    grep -Fq Healthy "${evidence_root}/exporter-health"; then
    break
  fi
  sleep 1
done
grep -Fq Healthy "${evidence_root}/exporter-health"
private_get "http://snmp_exporter:9116/metrics" "${evidence_root}/exporter-metrics"
grep -Fq 'snmp_exporter_build_info' "${evidence_root}/exporter-metrics"

valid_a_url='http://snmp_exporter:9116/snmp?target=synthetic-snmp-agent-1:1161&module=ncdp_if_mib&auth=ncdp_device_1_a'
if ! private_get "${valid_a_url}" "${evidence_root}/valid-a.metrics"; then
  docker logs "${NCDP_SNMP_EXPORTER_CONTAINER}" >"${evidence_root}/failed-exporter.log" 2>&1 || true
  docker logs "${project}-agent-1" >"${evidence_root}/failed-agent.log" 2>&1 || true
  leaked=false
  for sentinel in "${sentinels[@]}"; do
    if grep -R -F -- "${sentinel}" "${evidence_root}/failed-exporter.log" \
      "${evidence_root}/failed-agent.log" >/dev/null; then
      leaked=true
    fi
  done
  if [ "${leaked}" = false ]; then
    tail -30 "${evidence_root}/failed-exporter.log" >&2
    tail -30 "${evidence_root}/failed-agent.log" >&2
  else
    echo "synthetic SNMP failure logs contained credential material and were suppressed" >&2
  fi
  exit 2
fi
for metric in ifAdminStatus ifOperStatus ifHighSpeed ifHCInOctets ifHCOutOctets \
  ifInErrors ifOutErrors ifInDiscards ifOutDiscards \
  ifCounterDiscontinuityTime sysUpTime ifNumber ifTableLastChange; do
  grep -Fq "${metric}" "${evidence_root}/valid-a.metrics"
done
[ "$(private_status GET 'http://snmp_exporter:9116/snmp?target=synthetic-snmp-agent-1:1161&module=ncdp_if_mib&auth=ncdp_wrong_auth')" = 500 ]
[ "$(private_status GET 'http://snmp_exporter:9116/snmp?target=synthetic-snmp-agent-1:1161&module=ncdp_if_mib&auth=ncdp_wrong_privacy')" = 500 ]
[ "$(private_status GET 'http://snmp_exporter:9116/snmp?target=synthetic-snmp-agent-1:1161&module=ncdp_if_mib&auth=ncdp_unknown')" = 400 ]
[ "$(private_status GET 'http://snmp_exporter:9116/snmp?target=synthetic-unreachable:1161&module=ncdp_if_mib&auth=ncdp_device_1_a')" = 500 ]

inspection_file=${evidence_root}/container-inspection.json
docker inspect \
  "${NCDP_PROMETHEUS_CONTAINER}" "${NCDP_BLACKBOX_CONTAINER}" \
  "${NCDP_GRAFANA_CONTAINER}" "${NCDP_ALERTMANAGER_CONTAINER}" \
  "${NCDP_RECEIVER_CONTAINER}" "${NCDP_SNMP_EXPORTER_CONTAINER}" \
  >"${inspection_file}"
prometheus_image_id=$(docker image inspect "${prometheus_image}" --format '{{.Id}}')
blackbox_image_id=$(docker image inspect 'prom/blackbox-exporter:v0.27.0@sha256:a50c4c0eda297baa1678cd4dc4712a67fdea713b832d43ce7fcc5f9bea05094d' --format '{{.Id}}')
grafana_image_id=$(docker image inspect 'grafana/grafana:12.1.1@sha256:a1701c2180249361737a99a01bc770db39381640e4d631825d38ff4535efa47d' --format '{{.Id}}')
alertmanager_image_id=$(docker image inspect 'prom/alertmanager:v0.29.0@sha256:88743b63b3e09ea6e31e140ced5bf45f4a8e82c617c2a963f78841f4995ad1d7' --format '{{.Id}}')
receiver_image_id=$(docker image inspect 'python:3.12.13-slim@sha256:2c941e860699f878900b0edc2403613c234d4b32eda3cc9fa7036991a2a63c4a' --format '{{.Id}}')
export NCDP_TEST_PROMETHEUS_IMAGE_ID=${prometheus_image_id}
export NCDP_TEST_BLACKBOX_IMAGE_ID=${blackbox_image_id}
export NCDP_TEST_GRAFANA_IMAGE_ID=${grafana_image_id}
export NCDP_TEST_ALERTMANAGER_IMAGE_ID=${alertmanager_image_id}
export NCDP_TEST_RECEIVER_IMAGE_ID=${receiver_image_id}
export NCDP_TEST_EXPORTER_IMAGE_ID=${exporter_image_id}
export NCDP_TEST_PROJECT=${project}
export NCDP_TEST_TELEMETRY_NETWORK=${telemetry_network}
export NCDP_TEST_SNMP_CONTROL_NETWORK=${snmp_control_network}
export NCDP_TEST_SNMP_DEVICE_NETWORK=${snmp_device_network}
export NCDP_TEST_PROMETHEUS_PORT=${prometheus_port}
export NCDP_TEST_GRAFANA_PORT=${grafana_port}
export NCDP_TEST_CONFIG_ROOT=${config_root}
export NCDP_TEST_STATE_ROOT=${state_root}
export NCDP_TEST_RUNTIME_ROOT=${runtime_root}
export NCDP_TEST_MODULE_ROOT=${module_root}
export NCDP_TEST_AUTH_ROOT=${auth_root}
docker run --rm --user "${uid}:${gid}" \
  -e NCDP_TEST_PROMETHEUS_IMAGE_ID -e NCDP_TEST_BLACKBOX_IMAGE_ID \
  -e NCDP_TEST_GRAFANA_IMAGE_ID -e NCDP_TEST_ALERTMANAGER_IMAGE_ID \
  -e NCDP_TEST_RECEIVER_IMAGE_ID -e NCDP_TEST_EXPORTER_IMAGE_ID \
  -e NCDP_TEST_PROJECT -e NCDP_TEST_TELEMETRY_NETWORK \
  -e NCDP_TEST_SNMP_CONTROL_NETWORK -e NCDP_TEST_SNMP_DEVICE_NETWORK \
  -e NCDP_TEST_PROMETHEUS_PORT \
  -e NCDP_TEST_GRAFANA_PORT -e NCDP_TEST_CONFIG_ROOT \
  -e NCDP_TEST_STATE_ROOT -e NCDP_TEST_RUNTIME_ROOT \
  -e NCDP_TEST_MODULE_ROOT -e NCDP_TEST_AUTH_ROOT \
  -v "${test_root}:/test-root" "${quality_image}" \
  /app/.venv/bin/python -c '
import json, os
from pathlib import Path
from network_change_delivery.observability_service import (
    ALERTMANAGER_CONTAINER, BLACKBOX_CONTAINER, GRAFANA_CONTAINER,
    PROMETHEUS_CONTAINER, RECEIVER_CONTAINER, verify_container_definitions,
)
from network_change_delivery.snmp_service import verify_snmp_exporter_definition
values = json.loads(Path("/test-root/evidence/container-inspection.json").read_text())
services = {item["Config"]["Labels"]["com.docker.compose.service"]: item for item in values}
service_names = {
    "prometheus": PROMETHEUS_CONTAINER, "blackbox": BLACKBOX_CONTAINER,
    "grafana": GRAFANA_CONTAINER, "alertmanager": ALERTMANAGER_CONTAINER,
    "receiver": RECEIVER_CONTAINER,
}
five = {service_names[name]: item for name, item in services.items() if name in service_names}
verify_container_definitions(
    five,
    prometheus_image_id=os.environ["NCDP_TEST_PROMETHEUS_IMAGE_ID"],
    blackbox_image_id=os.environ["NCDP_TEST_BLACKBOX_IMAGE_ID"],
    grafana_image_id=os.environ["NCDP_TEST_GRAFANA_IMAGE_ID"],
    alertmanager_image_id=os.environ["NCDP_TEST_ALERTMANAGER_IMAGE_ID"],
    receiver_image_id=os.environ["NCDP_TEST_RECEIVER_IMAGE_ID"],
    config_root=Path(os.environ["NCDP_TEST_CONFIG_ROOT"]),
    state_root=Path(os.environ["NCDP_TEST_STATE_ROOT"]),
    runtime_root=Path(os.environ["NCDP_TEST_RUNTIME_ROOT"]),
    project_name=os.environ["NCDP_TEST_PROJECT"],
    network_name=os.environ["NCDP_TEST_TELEMETRY_NETWORK"],
    prometheus_additional_networks=frozenset({os.environ["NCDP_TEST_SNMP_CONTROL_NETWORK"]}),
    prometheus_host_port=os.environ["NCDP_TEST_PROMETHEUS_PORT"],
    grafana_host_port=os.environ["NCDP_TEST_GRAFANA_PORT"],
)
verify_snmp_exporter_definition(
    services["snmp_exporter"], image_id=os.environ["NCDP_TEST_EXPORTER_IMAGE_ID"],
    module_root=Path(os.environ["NCDP_TEST_MODULE_ROOT"]),
    auth_root=Path(os.environ["NCDP_TEST_AUTH_ROOT"]),
    project_name=os.environ["NCDP_TEST_PROJECT"],
    control_network_name=os.environ["NCDP_TEST_SNMP_CONTROL_NETWORK"],
    device_network_name=os.environ["NCDP_TEST_SNMP_DEVICE_NETWORK"],
    container_name=services["snmp_exporter"]["Name"].lstrip("/"),
)
'

for _ in $(seq 1 60); do
  query=$(curl --silent --fail --get --data-urlencode \
    'query=ifHCInOctets{job="ncdp-snmp-interface"}' \
    "http://127.0.0.1:${prometheus_port}/api/v1/query" || true)
  if jq -e '.data.result | length == 2' >/dev/null 2>&1 <<<"${query}"; then
    break
  fi
  sleep 1
done
jq -e '
  .data.result | length == 2
  and ([.[].metric.instance] | sort == ["netbox:dcim.device:1","netbox:dcim.device:2"])
  and all(.[].metric;
    (.interface_id == "netbox:dcim.interface:101" or .interface_id == "netbox:dcim.interface:201")
    and .interface_name == "eth0"
    and has("ifName") == false
    and has("ifIndex") == false)
' >/dev/null <<<"${query}"
for scalar in sysUpTime ifNumber ifTableLastChange; do
  result=$(curl --silent --fail --get --data-urlencode \
    "query=${scalar}{job=\"ncdp-snmp-interface\"}" \
    "http://127.0.0.1:${prometheus_port}/api/v1/query")
  jq -e '.data.result | length == 2 and all(.[].metric; has("interface_id") == false)' \
    >/dev/null <<<"${result}"
done
all_metrics=$(curl --silent --fail --get --data-urlencode \
  'query={job="ncdp-snmp-interface"}' \
  "http://127.0.0.1:${prometheus_port}/api/v1/query")
if jq -e '.data.result[].metric | select(.interface_name == "lo")' \
  >/dev/null 2>&1 <<<"${all_metrics}"; then
  echo "unmanaged SNMP interface was not dropped" >&2
  exit 2
fi
if grep -Eq 'ifInOctets|ifOutOctets|ifAlias|ifDescr' <<<"${all_metrics}"; then
  echo "SNMP metric closure expanded" >&2
  exit 2
fi
for sentinel in "${sentinels[@]}"; do
  if grep -F -- "${sentinel}" <<<"${all_metrics}" >/dev/null; then
    echo "synthetic SNMP credential entered metric results" >&2
    exit 2
  fi
done
blackbox_up=$(curl --silent --fail --get --data-urlencode \
  'query=up{job="ncdp-blackbox-exporter"}' \
  "http://127.0.0.1:${prometheus_port}/api/v1/query")
jq -e '.data.result | length == 1 and .[0].value[1] == "1"' \
  >/dev/null <<<"${blackbox_up}"

exporter_container_before=$(docker inspect "${NCDP_SNMP_EXPORTER_CONTAINER}" --format '{{.Id}}')
write_auth_b "${test_root}/auth-b.yml"
quality_python /app/scripts/observability/prepare_snmp_synthetic.py publish-auth \
  --directory /test-root/auth --source /test-root/auth-b.yml
quality_python /app/scripts/observability/prepare_snmp_synthetic.py publish-targets \
  --state-root /test-root/state --generation b
[ "$(private_status POST 'http://snmp_exporter:9116/-/reload')" = 200 ]
valid_b_url='http://snmp_exporter:9116/snmp?target=synthetic-snmp-agent-1:1161&module=ncdp_if_mib&auth=ncdp_device_1_b'
private_get "${valid_b_url}" "${evidence_root}/valid-b.metrics"
[ "$(private_status GET "${valid_a_url}")" = 400 ]
exporter_container_after=$(docker inspect "${NCDP_SNMP_EXPORTER_CONTAINER}" --format '{{.Id}}')
[ "${exporter_container_before}" = "${exporter_container_after}" ]

cp "${auth_root}/snmp-auth.yml" "${test_root}/valid-b-saved.yml"
printf 'auths:\n  invalid: true\n' >"${auth_root}/.invalid.yml"
chmod 0600 "${auth_root}/.invalid.yml"
mv "${auth_root}/.invalid.yml" "${auth_root}/snmp-auth.yml"
[ "$(private_status POST 'http://snmp_exporter:9116/-/reload')" = 500 ]
private_get "${valid_b_url}" "${evidence_root}/valid-b-after-rejected-reload.metrics"
mv "${test_root}/valid-b-saved.yml" "${auth_root}/snmp-auth.yml"
[ "$(private_status POST 'http://snmp_exporter:9116/-/reload')" = 200 ]

docker stop "${project}-agent-2" >/dev/null
for _ in $(seq 1 20); do
  isolation=$(curl --silent --fail --get --data-urlencode \
    'query=up{job="ncdp-snmp-interface"}' \
    "http://127.0.0.1:${prometheus_port}/api/v1/query" || true)
  if jq -e '
    any(.data.result[]; .metric.instance == "netbox:dcim.device:1" and .value[1] == "1")
    and any(.data.result[]; .metric.instance == "netbox:dcim.device:2" and .value[1] == "0")
  ' >/dev/null 2>&1 <<<"${isolation}"; then
    break
  fi
  sleep 5
done
jq -e '
  any(.data.result[]; .metric.instance == "netbox:dcim.device:1" and .value[1] == "1")
  and any(.data.result[]; .metric.instance == "netbox:dcim.device:2" and .value[1] == "0")
' >/dev/null <<<"${isolation}"
docker start "${project}-agent-2" >/dev/null

# The private `/config` endpoint exposes the controlled SNMPv3 principal while
# redacting both confidentiality-bearing passphrases. Do not persist the response.
docker run --rm --network "${snmp_control_network}" "${quality_image}" \
  /app/.venv/bin/python -c '
import sys, urllib.request
content = urllib.request.urlopen("http://snmp_exporter:9116/config", timeout=10).read()
for username in sys.argv[1:3]:
    assert username.encode() in content
for secret in sys.argv[3:]:
    assert secret.encode() not in content
assert content.count(b"<secret>") >= 4
' "${username_1_b}" "${username_2_b}" \
  "${auth_1_b}" "${privacy_1_b}" "${auth_2_b}" "${privacy_2_b}"

docker inspect "${NCDP_SNMP_EXPORTER_CONTAINER}" >"${evidence_root}/exporter-inspect.json"
docker inspect "${NCDP_PROMETHEUS_CONTAINER}" >"${evidence_root}/prometheus-inspect.json"
docker logs "${NCDP_SNMP_EXPORTER_CONTAINER}" >"${evidence_root}/exporter.log" 2>&1
docker logs "${NCDP_PROMETHEUS_CONTAINER}" >"${evidence_root}/prometheus.log" 2>&1
docker logs "${project}-agent-1" >"${evidence_root}/agent-1.log" 2>&1
docker logs "${project}-agent-2" >"${evidence_root}/agent-2.log" 2>&1
cp "${state_root}/discovery/snmp-targets.json" "${evidence_root}/snmp-targets.json"
cp "${config_root}/prometheus.yml" "${evidence_root}/prometheus.yml"
for index in "${!sentinels[@]}"; do
  while IFS= read -r -d '' evidence_file; do
    if grep -F -- "${sentinels[${index}]}" "${evidence_file}" >/dev/null; then
      echo "synthetic SNMP credential ${sentinel_labels[${index}]} leaked to ${evidence_file#"${evidence_root}/"}" >&2
      exit 2
    fi
  done < <(find "${evidence_root}" -type f -print0)
done

agent_version=$(docker run --rm --entrypoint /usr/bin/dpkg-query "${agent_image}" \
  -W '-f=${Version}' snmpd)
printf 'SNMP exporter image ID: %s (%s)\n' "${exporter_image_id}" "${exporter_platform}"
printf 'Synthetic agent image ID: %s (%s; %s)\n' \
  "${agent_image_id}" "${agent_platform}" "${agent_version}"

docker rm -f "${project}-agent-1" "${project}-agent-2" >/dev/null
"${compose[@]}" down --volumes --remove-orphans >/dev/null
if docker container ls -a --format '{{.Names}}' | grep -Fq "${project}" || \
  docker network ls --format '{{.Name}}' | grep -Fq "${project}" || \
  docker volume ls --format '{{.Name}}' | grep -Fq "${project}"; then
  echo "synthetic SNMP cleanup rejected" >&2
  exit 2
fi
rm -rf "${test_root}"
[ ! -e "${test_root}" ]
trap - EXIT
echo "synthetic SNMPv3 validation: PASS (two-agent protocol fixture, split control/device networks, authPriv SHA256/AES128, directory rotation/reload, normalized Prometheus telemetry, secret scan, management-service runtime preserved)"
