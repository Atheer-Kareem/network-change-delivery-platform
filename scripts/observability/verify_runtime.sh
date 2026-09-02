#!/bin/bash
set -euo pipefail

root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
quality_image=${NCDP_QUALITY_IMAGE:?NCDP_QUALITY_IMAGE required}
project="ncdp-observability-11b-test-${BUILDKITE_BUILD_NUMBER:-$$}"
network="${project}-telemetry"
prometheus_image='prom/prometheus:v3.14.0@sha256:5ce7540c3c00ef4ab0c9d2c995c6a5b9c421f44b4a115d97a2c7af3b1c21cbb0'
blackbox_image='prom/blackbox-exporter:v0.27.0@sha256:a50c4c0eda297baa1678cd4dc4712a67fdea713b832d43ce7fcc5f9bea05094d'
grafana_image='grafana/grafana:12.1.1@sha256:a1701c2180249361737a99a01bc770db39381640e4d631825d38ff4535efa47d'
alertmanager_image='prom/alertmanager:v0.29.0@sha256:88743b63b3e09ea6e31e140ced5bf45f4a8e82c617c2a963f78841f4995ad1d7'
receiver_image='python:3.12.13-slim@sha256:2c941e860699f878900b0edc2403613c234d4b32eda3cc9fa7036991a2a63c4a'
uid=$(id -u)
gid=$(id -g)
[ "${uid}" -gt 0 ] && [ "${gid}" -gt 0 ]

export NCDP_OBSERVABILITY_NETWORK="${network}"
export NCDP_PROMETHEUS_PORT=$((19090 + ${BUILDKITE_BUILD_NUMBER:-0} % 100))
export NCDP_GRAFANA_PORT=$((13000 + ${BUILDKITE_BUILD_NUMBER:-0} % 100))
export NCDP_RECEIVER_PORT=$((18080 + ${BUILDKITE_BUILD_NUMBER:-0} % 100))
export NCDP_PROMETHEUS_CONTAINER="${project}-prometheus"
export NCDP_BLACKBOX_CONTAINER="${project}-blackbox"
export NCDP_GRAFANA_CONTAINER="${project}-grafana"
export NCDP_ALERTMANAGER_CONTAINER="${project}-alertmanager"
export NCDP_RECEIVER_CONTAINER="${project}-receiver"

test_root=$(mktemp -d)
config_root=${test_root}/config
runtime_root=${test_root}/runtime
state_root=${test_root}/state
export NCDP_OBSERVABILITY_RUNTIME_ROOT="${runtime_root}"

quality_python() {
  docker run --rm \
    --user "${uid}:${gid}" \
    -e NCDP_TEST_STATE_ROOT=/test-root/state \
    -e NCDP_EXPECTED_UID="${uid}" \
    -e NCDP_EXPECTED_GID="${gid}" \
    -e NCDP_TEST_CISCO_IP \
    -e NCDP_TEST_JUNOS_IP \
    -e NCDP_TEST_CONFIG_ROOT="${config_root}" \
    -e NCDP_TEST_RUNTIME_ROOT="${runtime_root}" \
    -e NCDP_TEST_HOST_STATE_ROOT="${state_root}" \
    -e NCDP_TEST_PROJECT="${project}" \
    -e NCDP_TEST_NETWORK="${network}" \
    -e NCDP_TEST_PROMETHEUS_PORT="${NCDP_PROMETHEUS_PORT}" \
    -e NCDP_TEST_GRAFANA_PORT="${NCDP_GRAFANA_PORT}" \
    -e NCDP_TEST_PROMETHEUS_IMAGE_ID="${prometheus_image_id:-}" \
    -e NCDP_TEST_BLACKBOX_IMAGE_ID="${blackbox_image_id:-}" \
    -e NCDP_TEST_GRAFANA_IMAGE_ID="${grafana_image_id:-}" \
    -e NCDP_TEST_ALERTMANAGER_IMAGE_ID="${alertmanager_image_id:-}" \
    -e NCDP_TEST_RECEIVER_IMAGE_ID="${receiver_image_id:-}" \
    -v "${test_root}:/test-root" \
    "${quality_image}" /app/.venv/bin/python "$@"
}

cleanup() {
  docker rm -f "${project}-test-cisco" "${project}-test-junos" >/dev/null 2>&1 || true
  NCDP_OBSERVABILITY_UID=${uid} \
  NCDP_OBSERVABILITY_GID=${gid} \
  NCDP_OBSERVABILITY_CONFIG_ROOT=${config_root} \
  NCDP_OBSERVABILITY_STATE_ROOT=${state_root} \
    docker compose --project-name "${project}" \
      --file "${root}/infrastructure/observability/compose.yaml" down --volumes \
      >/dev/null 2>&1 || true
  rm -rf "${test_root}"
}
trap cleanup EXIT

pull_and_verify_image() {
  local exact_ref=$1
  local details image_id image_platform
  if [[ ! "${exact_ref}" =~ ^[^@]+@sha256:[0-9a-f]{64}$ ]]; then
    echo "observability image reference is not an exact digest: ${exact_ref}" >&2
    exit 2
  fi
  docker pull --platform linux/arm64 "${exact_ref}" >/dev/null
  details=$(docker image inspect "${exact_ref}" --format '{{.Id}} {{.Os}}/{{.Architecture}}')
  read -r image_id image_platform <<<"${details}"
  if [[ ! "${image_id}" =~ ^sha256:[0-9a-f]{64}$ ]] || [ "${image_platform}" != linux/arm64 ]; then
    echo "observability image inspection rejected: ${exact_ref}" >&2
    exit 2
  fi
  printf '%s\n' "${image_id}"
}

# Resolve every reviewed multi-arch index to a verified local Linux/ARM64 image
# before Compose is allowed to start with its intentional pull_policy: never.
prometheus_image_id=$(pull_and_verify_image "${prometheus_image}")
blackbox_image_id=$(pull_and_verify_image "${blackbox_image}")
grafana_image_id=$(pull_and_verify_image "${grafana_image}")
alertmanager_image_id=$(pull_and_verify_image "${alertmanager_image}")
receiver_image_id=$(pull_and_verify_image "${receiver_image}")

mkdir -p "${config_root}" "${runtime_root}/rules" "${runtime_root}/alertmanager" \
  "${runtime_root}/grafana/provisioning/datasources" \
  "${runtime_root}/grafana/provisioning/dashboards" \
  "${runtime_root}/grafana/dashboards" "${runtime_root}/receiver" \
  "${state_root}/runtime" "${state_root}/discovery" "${state_root}/control" \
  "${state_root}/operator" "${state_root}/prometheus" "${state_root}/grafana" \
  "${state_root}/alertmanager"
chmod 0700 "${config_root}" "${runtime_root}" "${runtime_root}/rules" \
  "${runtime_root}/alertmanager" "${runtime_root}/grafana" \
  "${runtime_root}/grafana/provisioning" \
  "${runtime_root}/grafana/provisioning/datasources" \
  "${runtime_root}/grafana/provisioning/dashboards" \
  "${runtime_root}/grafana/dashboards" "${runtime_root}/receiver" \
  "${state_root}" "${state_root}/runtime" "${state_root}/discovery" \
  "${state_root}/control" "${state_root}/operator" "${state_root}/prometheus" \
  "${state_root}/grafana" "${state_root}/alertmanager"
cp "${root}/infrastructure/observability/prometheus.yml" "${config_root}/prometheus.yml"
cp "${root}/infrastructure/observability/blackbox.yml" "${config_root}/blackbox.yml"
cp "${root}/infrastructure/observability/rules/11b-alerts.yml" "${runtime_root}/rules/11b-alerts.yml"
cp "${root}/infrastructure/observability/rules/11b-alerts.test.yml" "${runtime_root}/rules/11b-alerts.test.yml"
cp "${root}/infrastructure/observability/alertmanager.yml" "${runtime_root}/alertmanager/alertmanager.yml"
cp "${root}/infrastructure/observability/grafana/provisioning/datasources/prometheus.yml" "${runtime_root}/grafana/provisioning/datasources/prometheus.yml"
cp "${root}/infrastructure/observability/grafana/provisioning/dashboards/dashboards.yml" "${runtime_root}/grafana/provisioning/dashboards/dashboards.yml"
cp "${root}/infrastructure/observability/grafana/dashboards/ncdp-management-reachability.json" "${runtime_root}/grafana/dashboards/ncdp-management-reachability.json"
cp "${root}/scripts/observability/demo_receiver.py" "${runtime_root}/receiver/demo_receiver.py"
chmod 0600 "${config_root}/prometheus.yml" "${config_root}/blackbox.yml" \
  "${runtime_root}/rules/11b-alerts.yml" "${runtime_root}/rules/11b-alerts.test.yml" \
  "${runtime_root}/alertmanager/alertmanager.yml" \
  "${runtime_root}/grafana/provisioning/datasources/prometheus.yml" \
  "${runtime_root}/grafana/provisioning/dashboards/dashboards.yml" \
  "${runtime_root}/grafana/dashboards/ncdp-management-reachability.json" \
  "${runtime_root}/receiver/demo_receiver.py"

quality_python -c 'import os; assert os.getuid() == int(os.environ["NCDP_EXPECTED_UID"]); assert os.getgid() == int(os.environ["NCDP_EXPECTED_GID"])' \
  </dev/null

docker run --rm --platform linux/arm64 --read-only --cap-drop ALL \
  --security-opt no-new-privileges --user "${uid}:${gid}" \
  -v "${config_root}/prometheus.yml:/etc/ncdp/prometheus.yml:ro" \
  -v "${runtime_root}/rules:/etc/ncdp/rules:ro" \
  --entrypoint /bin/promtool "${prometheus_image}" \
  check config /etc/ncdp/prometheus.yml
docker run --rm --platform linux/arm64 --read-only --cap-drop ALL \
  --security-opt no-new-privileges --user "${uid}:${gid}" \
  -v "${runtime_root}/rules:/etc/ncdp/rules:ro" \
  --entrypoint /bin/promtool "${prometheus_image}" \
  check rules /etc/ncdp/rules/11b-alerts.yml
docker run --rm --platform linux/arm64 --read-only --cap-drop ALL \
  --security-opt no-new-privileges --user "${uid}:${gid}" \
  --tmpfs /tmp:rw,noexec,nosuid,nodev,size=16m \
  --workdir /etc/ncdp/rules -v "${runtime_root}/rules:/etc/ncdp/rules:ro" \
  --entrypoint /bin/promtool "${prometheus_image}" \
  test rules 11b-alerts.test.yml
docker run --rm --platform linux/arm64 --read-only --cap-drop ALL \
  --security-opt no-new-privileges --user "${uid}:${gid}" \
  -v "${runtime_root}/alertmanager/alertmanager.yml:/etc/ncdp/alertmanager.yml:ro" \
  --entrypoint /bin/amtool "${alertmanager_image}" \
  check-config /etc/ncdp/alertmanager.yml

quality_python -c 'import os; from pathlib import Path; from network_change_delivery.observability_targets import TargetGenerationState,publish_generation; publish_generation(Path(os.environ["NCDP_TEST_STATE_ROOT"]),state=TargetGenerationState.RETIRED)'

NCDP_OBSERVABILITY_UID=${uid} \
NCDP_OBSERVABILITY_GID=${gid} \
NCDP_OBSERVABILITY_CONFIG_ROOT=${config_root} \
NCDP_OBSERVABILITY_STATE_ROOT=${state_root} \
  docker compose --project-name "${project}" \
    --file "${root}/infrastructure/observability/compose.yaml" \
    up --detach --pull never --no-build

containers=(
  "${NCDP_PROMETHEUS_CONTAINER}"
  "${NCDP_BLACKBOX_CONTAINER}"
  "${NCDP_GRAFANA_CONTAINER}"
  "${NCDP_ALERTMANAGER_CONTAINER}"
  "${NCDP_RECEIVER_CONTAINER}"
)
for _ in $(seq 1 60); do
  running=0
  for container in "${containers[@]}"; do
    if [ "$(docker inspect "${container}" --format '{{.State.Running}}' 2>/dev/null || true)" = true ]; then
      running=$((running + 1))
    fi
  done
  [ "${running}" -eq 5 ] && break
  sleep 1
done
if [ "${running}" -ne 5 ]; then
  docker compose --project-name "${project}" \
    --file "${root}/infrastructure/observability/compose.yaml" ps >&2
  docker compose --project-name "${project}" \
    --file "${root}/infrastructure/observability/compose.yaml" logs >&2
  exit 2
fi

verify_container() {
  local container=$1 service=$2 exact_ref=$3 image_id=$4 expected_binds=$5
  docker inspect "${container}" | jq -e \
    --arg project "${project}" \
    --arg service "${service}" \
    --arg exact_ref "${exact_ref}" \
    --arg image_id "${image_id}" \
    --arg user "${uid}:${gid}" \
    --arg network "${network}" \
    --argjson expected_binds "${expected_binds}" '
      length == 1
      and .[0].State.Running == true
      and .[0].Config.Image == $exact_ref
      and .[0].Image == $image_id
      and .[0].Config.User == $user
      and .[0].Config.Labels["com.docker.compose.project"] == $project
      and .[0].Config.Labels["com.docker.compose.service"] == $service
      and .[0].HostConfig.ReadonlyRootfs == true
      and .[0].HostConfig.RestartPolicy.Name == "no"
      and .[0].HostConfig.CapDrop == ["ALL"]
      and .[0].HostConfig.SecurityOpt == ["no-new-privileges:true"]
      and .[0].HostConfig.NetworkMode == $network
      and ((.[0].HostConfig.Binds | sort) == ($expected_binds | sort))
      and (.[0].NetworkSettings.Networks | has($network))
    ' >/dev/null
}

verify_container "${NCDP_PROMETHEUS_CONTAINER}" prometheus "${prometheus_image}" \
  "${prometheus_image_id}" "$(jq -cn \
    --arg a "${config_root}/prometheus.yml:/etc/ncdp/prometheus.yml:ro" \
    --arg b "${runtime_root}/rules:/etc/ncdp/rules:ro" \
    --arg c "${state_root}/discovery:/etc/ncdp/targets:ro" \
    --arg d "${state_root}/prometheus:/prometheus:rw" '[ $a, $b, $c, $d ]')"
verify_container "${NCDP_BLACKBOX_CONTAINER}" blackbox "${blackbox_image}" \
  "${blackbox_image_id}" "$(jq -cn \
    --arg a "${config_root}/blackbox.yml:/etc/ncdp/blackbox.yml:ro" '[ $a ]')"
verify_container "${NCDP_GRAFANA_CONTAINER}" grafana "${grafana_image}" \
  "${grafana_image_id}" "$(jq -cn \
    --arg a "${runtime_root}/grafana/provisioning:/etc/grafana/provisioning:ro" \
    --arg b "${runtime_root}/grafana/dashboards:/etc/grafana/dashboards:ro" \
    --arg c "${state_root}/grafana:/var/lib/grafana:rw" '[ $a, $b, $c ]')"
verify_container "${NCDP_ALERTMANAGER_CONTAINER}" alertmanager "${alertmanager_image}" \
  "${alertmanager_image_id}" "$(jq -cn \
    --arg a "${runtime_root}/alertmanager/alertmanager.yml:/etc/ncdp/alertmanager.yml:ro" \
    --arg b "${state_root}/alertmanager:/alertmanager:rw" '[ $a, $b ]')"
verify_container "${NCDP_RECEIVER_CONTAINER}" receiver "${receiver_image}" \
  "${receiver_image_id}" "$(jq -cn \
    --arg a "${runtime_root}/receiver/demo_receiver.py:/opt/ncdp/demo_receiver.py:ro" '[ $a ]')"

docker inspect "${NCDP_PROMETHEUS_CONTAINER}" | jq -e \
  --arg port "${NCDP_PROMETHEUS_PORT}" \
  '.[0].HostConfig.PortBindings == {"9090/tcp":[{"HostIp":"127.0.0.1","HostPort":$port}]}' \
  >/dev/null
docker inspect "${NCDP_GRAFANA_CONTAINER}" | jq -e \
  --arg port "${NCDP_GRAFANA_PORT}" \
  '.[0].HostConfig.PortBindings == {"3000/tcp":[{"HostIp":"127.0.0.1","HostPort":$port}]}' \
  >/dev/null
for container in "${NCDP_BLACKBOX_CONTAINER}" "${NCDP_ALERTMANAGER_CONTAINER}" "${NCDP_RECEIVER_CONTAINER}"; do
  docker inspect "${container}" | jq -e \
    '((.[0].HostConfig.PortBindings // {}) | length) == 0' >/dev/null
done

inspection_file=${state_root}/container-inspection.json
docker inspect "${containers[@]}" > "${inspection_file}"
chmod 0600 "${inspection_file}"
quality_python -c '
import json
import os
from pathlib import Path
from network_change_delivery.observability_service import (
    ALERTMANAGER_CONTAINER,
    BLACKBOX_CONTAINER,
    GRAFANA_CONTAINER,
    PROMETHEUS_CONTAINER,
    RECEIVER_CONTAINER,
    verify_container_definitions,
)
service_names = {
    "prometheus": PROMETHEUS_CONTAINER,
    "blackbox": BLACKBOX_CONTAINER,
    "grafana": GRAFANA_CONTAINER,
    "alertmanager": ALERTMANAGER_CONTAINER,
    "receiver": RECEIVER_CONTAINER,
}
with open("/test-root/state/container-inspection.json", encoding="utf-8") as stream:
    values = json.load(stream)
inspected = {
    service_names[item["Config"]["Labels"]["com.docker.compose.service"]]: item
    for item in values
}
verify_container_definitions(
    inspected,
    prometheus_image_id=os.environ["NCDP_TEST_PROMETHEUS_IMAGE_ID"],
    blackbox_image_id=os.environ["NCDP_TEST_BLACKBOX_IMAGE_ID"],
    grafana_image_id=os.environ["NCDP_TEST_GRAFANA_IMAGE_ID"],
    alertmanager_image_id=os.environ["NCDP_TEST_ALERTMANAGER_IMAGE_ID"],
    receiver_image_id=os.environ["NCDP_TEST_RECEIVER_IMAGE_ID"],
    config_root=Path(os.environ["NCDP_TEST_CONFIG_ROOT"]),
    runtime_root=Path(os.environ["NCDP_TEST_RUNTIME_ROOT"]),
    state_root=Path(os.environ["NCDP_TEST_HOST_STATE_ROOT"]),
    project_name=os.environ["NCDP_TEST_PROJECT"],
    network_name=os.environ["NCDP_TEST_NETWORK"],
    prometheus_host_port=os.environ["NCDP_TEST_PROMETHEUS_PORT"],
    grafana_host_port=os.environ["NCDP_TEST_GRAFANA_PORT"],
)
'
rm "${inspection_file}"

for _ in $(seq 1 60); do
  grafana_health=$(curl --silent --fail \
    "http://127.0.0.1:${NCDP_GRAFANA_PORT}/api/health" || true)
  if jq -e '.database == "ok"' >/dev/null 2>&1 <<<"${grafana_health}"; then
    break
  fi
  sleep 1
done
jq -e '.database == "ok"' >/dev/null <<<"${grafana_health}"
curl --silent --fail \
  "http://127.0.0.1:${NCDP_GRAFANA_PORT}/api/dashboards/uid/ncdp-management-reachability" | \
  jq -e '
    .dashboard.uid == "ncdp-management-reachability"
    and .dashboard.title == "NCDP Management Reachability"
    and .dashboard.editable == false
    and .meta.folderTitle == "NCDP"
  ' >/dev/null
curl --silent --fail \
  "http://127.0.0.1:${NCDP_GRAFANA_PORT}/api/datasources/uid/ncdp-prometheus" | \
  jq -e '
    .uid == "ncdp-prometheus"
    and .type == "prometheus"
    and .url == "http://prometheus:9090"
    and .isDefault == true
    and .readOnly == true
  ' >/dev/null

docker run --detach --name "${project}-test-cisco" \
  --network "${network}" --read-only --cap-drop ALL \
  --security-opt no-new-privileges "${receiver_image}" \
  python -m http.server 22 >/dev/null
docker run --detach --name "${project}-test-junos" \
  --network "${network}" --read-only --cap-drop ALL \
  --security-opt no-new-privileges "${receiver_image}" \
  python -m http.server 830 >/dev/null

cisco_ip=$(docker inspect "${project}-test-cisco" --format '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}')
junos_ip=$(docker inspect "${project}-test-junos" --format '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}')
NCDP_TEST_CISCO_IP=${cisco_ip} NCDP_TEST_JUNOS_IP=${junos_ip} quality_python -c '
import os
from pathlib import Path
from types import SimpleNamespace
from network_change_delivery.architecture_contracts import AutomationProfileID, NetworkOS
from network_change_delivery.observability_targets import TargetGenerationState, publish_generation, targets_from_inventory

class Device(SimpleNamespace):
    def live_read_only_target(self):
        return SimpleNamespace(host=self.host, port=self.port)

devices = (
    Device(inventory_object_id="netbox:dcim.device:1", logical_name="core-02", platform=SimpleNamespace(slug="cisco-ios-xe"), network_os=NetworkOS.IOSXE, automation_profile_id=AutomationProfileID.CAT8000V_IOSXE, host=os.environ["NCDP_TEST_CISCO_IP"], port=22),
    Device(inventory_object_id="netbox:dcim.device:2", logical_name="edge-junos-01", platform=SimpleNamespace(slug="juniper-junos"), network_os=NetworkOS.JUNOS, automation_profile_id=AutomationProfileID.VJUNOS_ROUTER, host=os.environ["NCDP_TEST_JUNOS_IP"], port=830),
    Device(inventory_object_id="netbox:dcim.device:8", logical_name="transit-ios-01", platform=SimpleNamespace(slug="cisco-ios"), network_os=NetworkOS.IOS, automation_profile_id=AutomationProfileID.IOSV_159_3_M12, host=os.environ["NCDP_TEST_CISCO_IP"], port=22),
    Device(inventory_object_id="netbox:dcim.device:9", logical_name="access-sw-01", platform=SimpleNamespace(slug="cisco-ios"), network_os=NetworkOS.IOS, automation_profile_id=AutomationProfileID.IOSVL2_2020, host=os.environ["NCDP_TEST_CISCO_IP"], port=22),
)
inventory = SimpleNamespace(resolve_profiled_population=lambda: SimpleNamespace(devices=devices))
realization = SimpleNamespace(lab_id="11111111-1111-1111-1111-111111111111", digest="sha256:" + "a" * 64)
publish_generation(Path(os.environ["NCDP_TEST_STATE_ROOT"]), state=TargetGenerationState.ACTIVE, targets=targets_from_inventory(inventory), realization=realization)
'

for _ in $(seq 1 45); do
  result=$(curl --silent --fail --get --data-urlencode \
    'query=probe_success{job="ncdp-management-service"}' \
    "http://127.0.0.1:${NCDP_PROMETHEUS_PORT}/api/v1/query" || true)
  if jq -e '.data.result | length == 4 and all(.[]; .value[1] == "1")' \
    >/dev/null 2>&1 <<<"${result}"; then
    break
  fi
  sleep 1
done
jq -e '
  .data.result | length == 4
  and ([.[].metric.instance] | sort == ["netbox:dcim.device:1","netbox:dcim.device:2","netbox:dcim.device:8","netbox:dcim.device:9"])
  and all(.[].metric;
    (.device_name == "core-02" or .device_name == "edge-junos-01" or .device_name == "transit-ios-01" or .device_name == "access-sw-01")
    and (.platform == "cisco-ios-xe" or .platform == "juniper-junos" or .platform == "cisco-ios")
    and (.management_service == "ssh" or .management_service == "netconf")
    and .telemetry_source == "tcp_connect"
    and .environment == "operator_cml"
    and (.instance | startswith("netbox:dcim.device:")))
' >/dev/null <<<"${result}"
if grep -Eq "${cisco_ip}|${junos_ip}|11111111-1111" <<<"$(jq -c '.data.result[].metric' <<<"${result}")"; then
  echo "observability metric identity leaked private routing metadata" >&2
  exit 2
fi

docker stop "${project}-test-junos" >/dev/null
for _ in $(seq 1 180); do
  unreachable=$(curl --silent --fail --get --data-urlencode \
    'query=probe_success{job="ncdp-management-service",instance="netbox:dcim.device:2"}' \
    "http://127.0.0.1:${NCDP_PROMETHEUS_PORT}/api/v1/query" || true)
  firing=$(curl --silent --fail --get --data-urlencode \
    'query=ALERTS{alertname="NCDPManagementServiceDown",instance="netbox:dcim.device:2",alertstate="firing"}' \
    "http://127.0.0.1:${NCDP_PROMETHEUS_PORT}/api/v1/query" || true)
  if jq -e '.data.result | length == 1 and .[0].value[1] == "0"' \
    >/dev/null 2>&1 <<<"${unreachable}" && \
    jq -e '.data.result | length == 1 and .[0].value[1] == "1"' \
      >/dev/null 2>&1 <<<"${firing}" && \
    docker logs "${NCDP_RECEIVER_CONTAINER}" 2>&1 | grep -Fq '"status": "firing"'; then
    break
  fi
  sleep 1
done
jq -e '.data.result | length == 1 and .[0].value[1] == "0"' \
  >/dev/null <<<"${unreachable}"
jq -e '.data.result | length == 1 and .[0].value[1] == "1"' \
  >/dev/null <<<"${firing}"
alertmanager_alerts=$(docker exec "${NCDP_RECEIVER_CONTAINER}" python -c '
import urllib.request
print(urllib.request.urlopen("http://alertmanager:9093/api/v2/alerts", timeout=5).read().decode())
')
jq -e '
  any(.[].labels;
    .alertname == "NCDPManagementServiceDown"
    and .instance == "netbox:dcim.device:2")
' >/dev/null <<<"${alertmanager_alerts}"
docker logs "${NCDP_RECEIVER_CONTAINER}" 2>&1 | grep -Fq '"status": "firing"'

docker start "${project}-test-junos" >/dev/null
for _ in $(seq 1 150); do
  recovered=$(curl --silent --fail --get --data-urlencode \
    'query=probe_success{job="ncdp-management-service",instance="netbox:dcim.device:2"}' \
    "http://127.0.0.1:${NCDP_PROMETHEUS_PORT}/api/v1/query" || true)
  if jq -e '.data.result | length == 1 and .[0].value[1] == "1"' \
    >/dev/null 2>&1 <<<"${recovered}" && \
    docker logs "${NCDP_RECEIVER_CONTAINER}" 2>&1 | grep -Fq '"status": "resolved"'; then
    break
  fi
  sleep 1
done
jq -e '.data.result | length == 1 and .[0].value[1] == "1"' \
  >/dev/null <<<"${recovered}"
docker logs "${NCDP_RECEIVER_CONTAINER}" 2>&1 | grep -Fq '"status": "resolved"'

before=$(find "${state_root}/prometheus" -type f | wc -l | tr -d ' ')
NCDP_OBSERVABILITY_UID=${uid} \
NCDP_OBSERVABILITY_GID=${gid} \
NCDP_OBSERVABILITY_CONFIG_ROOT=${config_root} \
NCDP_OBSERVABILITY_STATE_ROOT=${state_root} \
  docker compose --project-name "${project}" \
    --file "${root}/infrastructure/observability/compose.yaml" \
    up --detach --force-recreate --pull never --no-build prometheus >/dev/null
after=$(find "${state_root}/prometheus" -type f | wc -l | tr -d ' ')
[ "${before}" -gt 0 ] && [ "${after}" -gt 0 ]

quality_python -c 'import os; from pathlib import Path; from network_change_delivery.observability_targets import TargetGenerationState,publish_generation; publish_generation(Path(os.environ["NCDP_TEST_STATE_ROOT"]),state=TargetGenerationState.RETIRED)'
for _ in $(seq 1 30); do
  active=$(curl --silent --fail "http://127.0.0.1:${NCDP_PROMETHEUS_PORT}/api/v1/targets" | \
    jq '[.data.activeTargets[] | select(.labels.job == "ncdp-management-service")] | length')
  [ "${active}" -eq 0 ] && break
  sleep 1
done
[ "${active}" -eq 0 ]
history=$(curl --silent --fail --get --data-urlencode \
  'query=count_over_time(probe_success{job="ncdp-management-service"}[10m])' \
  "http://127.0.0.1:${NCDP_PROMETHEUS_PORT}/api/v1/query")
jq -e '.data.result | length == 4 and all(.[].value[1]; tonumber > 0)' \
  >/dev/null <<<"${history}"

echo "observability 11B synthetic runtime: PASS (exact ARM64 images, config/rules, five hardened services, Grafana, profile-derived TCP 22/830 targets, FIRING/RESOLVED delivery, persistence, retirement)"
