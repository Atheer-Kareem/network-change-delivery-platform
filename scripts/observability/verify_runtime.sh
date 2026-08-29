#!/bin/bash
set -euo pipefail

root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
project="ncdp-observability-11b-test-${BUILDKITE_BUILD_NUMBER:-$$}"
network="${project}-telemetry"
export NCDP_OBSERVABILITY_NETWORK="${network}"
export NCDP_PROMETHEUS_PORT=$((19090 + ${BUILDKITE_BUILD_NUMBER:-0} % 100))
export NCDP_GRAFANA_PORT=$((13000 + ${BUILDKITE_BUILD_NUMBER:-0} % 100))
export NCDP_RECEIVER_PORT=$((18080 + ${BUILDKITE_BUILD_NUMBER:-0} % 100))

test_root=$(mktemp -d)
config_root=${test_root}/config
state_root=${test_root}/state
cleanup() {
  docker rm -f "${project}-test-cisco" "${project}-test-junos" >/dev/null 2>&1 || true
  NCDP_OBSERVABILITY_UID=$(id -u) \
  NCDP_OBSERVABILITY_GID=$(id -g) \
  NCDP_OBSERVABILITY_CONFIG_ROOT=${config_root} \
  NCDP_OBSERVABILITY_STATE_ROOT=${state_root} \
    docker compose --project-name "${project}" \
      --file "${root}/infrastructure/observability/compose.yaml" down --volumes \
      >/dev/null 2>&1 || true
  rm -rf "${test_root}"
}
trap cleanup EXIT

mkdir -p "${config_root}" "${state_root}/runtime" "${state_root}/discovery" "${state_root}/control" \
  "${state_root}/operator" "${state_root}/prometheus" "${state_root}/grafana" "${state_root}/alertmanager" \
  "${config_root}/rules" "${config_root}/grafana/provisioning/datasources" "${config_root}/grafana/provisioning/dashboards" "${config_root}/grafana/dashboards"
chmod 0700 "${config_root}" "${state_root}" "${state_root}/runtime" "${state_root}/discovery" \
  "${state_root}/control" "${state_root}/operator" "${state_root}/prometheus"
cp "${root}/infrastructure/observability/prometheus.yml" "${config_root}/prometheus.yml"
cp "${root}/infrastructure/observability/blackbox.yml" "${config_root}/blackbox.yml"
cp "${root}/infrastructure/observability/rules/11b-alerts.yml" "${config_root}/rules/11b-alerts.yml"
cp "${root}/infrastructure/observability/alertmanager.yml" "${config_root}/alertmanager.yml"
cp "${root}/infrastructure/observability/grafana/provisioning/datasources/prometheus.yml" "${config_root}/grafana/provisioning/datasources/prometheus.yml"
cp "${root}/infrastructure/observability/grafana/provisioning/dashboards/dashboards.yml" "${config_root}/grafana/provisioning/dashboards/dashboards.yml"
cp "${root}/infrastructure/observability/grafana/dashboards/ncdp-management-reachability.json" "${config_root}/grafana/dashboards/ncdp-management-reachability.json"
cp "${root}/scripts/observability/demo_receiver.py" "${config_root}/demo_receiver.py"
chmod 0600 "${config_root}/prometheus.yml" "${config_root}/blackbox.yml"

NCDP_TEST_STATE_ROOT=${state_root} UV_CACHE_DIR=/tmp/ncdp-uv-cache \
  uv run python -c 'import os; from pathlib import Path; from network_change_delivery.observability_targets import TargetGenerationState,publish_generation; publish_generation(Path(os.environ["NCDP_TEST_STATE_ROOT"]),state=TargetGenerationState.RETIRED)'

NCDP_OBSERVABILITY_UID=$(id -u) \
NCDP_OBSERVABILITY_GID=$(id -g) \
NCDP_OBSERVABILITY_CONFIG_ROOT=${config_root} \
NCDP_OBSERVABILITY_STATE_ROOT=${state_root} \
  docker compose --project-name "${project}" \
    --file "${root}/infrastructure/observability/compose.yaml" \
    up --detach --pull never --no-build

NCDP_TEST_PROMETHEUS_IMAGE_ID=$(docker image inspect \
  'prom/prometheus:v3.14.0@sha256:5ce7540c3c00ef4ab0c9d2c995c6a5b9c421f44b4a115d97a2c7af3b1c21cbb0' \
  --format '{{.Id}}') \
NCDP_TEST_BLACKBOX_IMAGE_ID=$(docker image inspect \
  'prom/blackbox-exporter:v0.27.0@sha256:a50c4c0eda297baa1678cd4dc4712a67fdea713b832d43ce7fcc5f9bea05094d' \
  --format '{{.Id}}') \
NCDP_OBSERVABILITY_CONFIG_ROOT=${config_root} \
NCDP_OBSERVABILITY_STATE_ROOT=${state_root} \
UV_CACHE_DIR=/tmp/ncdp-uv-cache \
  uv run python -c 'import os; from pathlib import Path; from network_change_delivery.observability_service import inspect_containers,verify_container_definitions; verify_container_definitions(inspect_containers(),prometheus_image_id=os.environ["NCDP_TEST_PROMETHEUS_IMAGE_ID"],blackbox_image_id=os.environ["NCDP_TEST_BLACKBOX_IMAGE_ID"],config_root=Path(os.environ["NCDP_OBSERVABILITY_CONFIG_ROOT"]),state_root=Path(os.environ["NCDP_OBSERVABILITY_STATE_ROOT"]))'

python_image='python:3.12-slim@sha256:2c941e860699f878900b0edc2403613c234d4b32eda3cc9fa7036991a2a63c4a'
docker run --detach --name "${project}-test-cisco" \
  --network "${network}" --read-only --cap-drop ALL \
  --security-opt no-new-privileges "${python_image}" \
  python -m http.server 22 >/dev/null
docker run --detach --name "${project}-test-junos" \
  --network "${network}" --read-only --cap-drop ALL \
  --security-opt no-new-privileges "${python_image}" \
  python -m http.server 830 >/dev/null

cisco_ip=$(docker inspect "${project}-test-cisco" --format '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}')
junos_ip=$(docker inspect "${project}-test-junos" --format '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}')
NCDP_TEST_STATE_ROOT=${state_root} NCDP_TEST_CISCO_IP=${cisco_ip} \
NCDP_TEST_JUNOS_IP=${junos_ip} UV_CACHE_DIR=/tmp/ncdp-uv-cache \
  uv run python -c 'import os; from pathlib import Path; from types import SimpleNamespace; from network_change_delivery.models import InventoryDevice; from network_change_delivery.observability_targets import TargetGenerationState,publish_generation,targets_from_inventory; devices=(InventoryDevice(name="core-02",host=os.environ["NCDP_TEST_CISCO_IP"],port=22,platform="cisco_iosxe",expected_hostname="core-02",inventory_source="netbox",inventory_object_id="netbox:dcim.device:1"),InventoryDevice(name="edge-junos-01",host=os.environ["NCDP_TEST_JUNOS_IP"],port=830,platform="junos",expected_hostname="edge-junos-01",inventory_source="netbox",inventory_object_id="netbox:dcim.device:2")); inventory=SimpleNamespace(resolve_managed_devices=lambda: devices); realization=SimpleNamespace(lab_id="11111111-1111-1111-1111-111111111111",digest="sha256:"+"a"*64); publish_generation(Path(os.environ["NCDP_TEST_STATE_ROOT"]),state=TargetGenerationState.ACTIVE,targets=targets_from_inventory(inventory),realization=realization)'

for _ in $(seq 1 45); do
  result=$(curl --silent --fail --get --data-urlencode \
    'query=probe_success{job="ncdp-management-service"}' \
    "http://127.0.0.1:${NCDP_PROMETHEUS_PORT}/api/v1/query" || true)
  if jq -e '.data.result | length == 2 and all(.[]; .value[1] == "1")' \
    >/dev/null 2>&1 <<<"${result}"; then
    break
  fi
  sleep 1
done
jq -e '
  .data.result | length == 2
  and ([.[].metric.instance] | sort == ["netbox:dcim.device:1","netbox:dcim.device:2"])
  and all(.[].metric;
    (.device_name == "core-02" or .device_name == "edge-junos-01")
    and (.platform == "cisco_iosxe" or .platform == "junos")
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
for _ in $(seq 1 30); do
  unreachable=$(curl --silent --fail --get --data-urlencode \
    'query=probe_success{job="ncdp-management-service",instance="netbox:dcim.device:2"}' \
    "http://127.0.0.1:${NCDP_PROMETHEUS_PORT}/api/v1/query" || true)
  if jq -e '.data.result | length == 1 and .[0].value[1] == "0"' \
    >/dev/null 2>&1 <<<"${unreachable}"; then
    break
  fi
  sleep 1
done
jq -e '.data.result | length == 1 and .[0].value[1] == "0"' \
  >/dev/null <<<"${unreachable}"
docker start "${project}-test-junos" >/dev/null

before=$(find "${state_root}/prometheus" -type f | wc -l | tr -d ' ')
NCDP_OBSERVABILITY_UID=$(id -u) \
NCDP_OBSERVABILITY_GID=$(id -g) \
NCDP_OBSERVABILITY_CONFIG_ROOT=${config_root} \
NCDP_OBSERVABILITY_STATE_ROOT=${state_root} \
  docker compose --project-name "${project}" \
    --file "${root}/infrastructure/observability/compose.yaml" \
    up --detach --force-recreate --pull never --no-build prometheus >/dev/null
after=$(find "${state_root}/prometheus" -type f | wc -l | tr -d ' ')
[ "${before}" -gt 0 ] && [ "${after}" -gt 0 ]

NCDP_TEST_STATE_ROOT=${state_root} UV_CACHE_DIR=/tmp/ncdp-uv-cache \
  uv run python -c 'import os; from pathlib import Path; from network_change_delivery.observability_targets import TargetGenerationState,publish_generation; publish_generation(Path(os.environ["NCDP_TEST_STATE_ROOT"]),state=TargetGenerationState.RETIRED)'
for _ in $(seq 1 30); do
  active=$(curl --silent --fail "http://127.0.0.1:${NCDP_PROMETHEUS_PORT}/api/v1/targets" | \
    jq '[.data.activeTargets[] | select(.labels.job == "ncdp-management-service")] | length')
  [ "${active}" -eq 0 ] && break
  sleep 1
done
[ "${active}" -eq 0 ]
history=$(curl --silent --fail --get --data-urlencode \
  'query=count_over_time(probe_success{job="ncdp-management-service"}[5m])' \
  "http://127.0.0.1:${NCDP_PROMETHEUS_PORT}/api/v1/query")
jq -e '.data.result | length == 2 and all(.[].value[1]; tonumber > 0)' \
  >/dev/null <<<"${history}"

echo "observability synthetic runtime: PASS (TCP 22/830, stable identity, persistence, retirement)"
