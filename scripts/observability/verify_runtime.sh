#!/bin/bash
set -euo pipefail

root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
quality_image=${NCDP_QUALITY_IMAGE:?NCDP_QUALITY_IMAGE required}
project="ncdp-observability-11b-test-${BUILDKITE_BUILD_NUMBER:-$$}"
network="${project}-telemetry"
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
quality_python() { docker run --rm -e NCDP_TEST_STATE_ROOT=/test-state -v "${state_root}:/test-state" "${quality_image}" /app/.venv/bin/python "$@"; }
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

mkdir -p "${config_root}" "${runtime_root}/rules" "${runtime_root}/alertmanager" "${runtime_root}/grafana/provisioning/datasources" "${runtime_root}/grafana/provisioning/dashboards" "${runtime_root}/grafana/dashboards" "${runtime_root}/receiver" "${state_root}/runtime" "${state_root}/discovery" "${state_root}/control" \
  "${state_root}/operator" "${state_root}/prometheus" "${state_root}/grafana" "${state_root}/alertmanager" \
  "${config_root}/rules" "${config_root}/grafana/provisioning/datasources" "${config_root}/grafana/provisioning/dashboards" "${config_root}/grafana/dashboards"
chmod 0700 "${config_root}" "${state_root}" "${state_root}/runtime" "${state_root}/discovery" \
  "${state_root}/control" "${state_root}/operator" "${state_root}/prometheus"
cp "${root}/infrastructure/observability/prometheus.yml" "${config_root}/prometheus.yml"
cp "${root}/infrastructure/observability/blackbox.yml" "${config_root}/blackbox.yml"
cp "${root}/infrastructure/observability/rules/11b-alerts.yml" "${runtime_root}/rules/11b-alerts.yml"
cp "${root}/infrastructure/observability/alertmanager.yml" "${runtime_root}/alertmanager/alertmanager.yml"
cp "${root}/infrastructure/observability/grafana/provisioning/datasources/prometheus.yml" "${runtime_root}/grafana/provisioning/datasources/prometheus.yml"
cp "${root}/infrastructure/observability/grafana/provisioning/dashboards/dashboards.yml" "${runtime_root}/grafana/provisioning/dashboards/dashboards.yml"
cp "${root}/infrastructure/observability/grafana/dashboards/ncdp-management-reachability.json" "${runtime_root}/grafana/dashboards/ncdp-management-reachability.json"
cp "${root}/scripts/observability/demo_receiver.py" "${runtime_root}/receiver/demo_receiver.py"
chmod 0600 "${config_root}/prometheus.yml" "${config_root}/blackbox.yml"

quality_python -c 'import os; from pathlib import Path; from network_change_delivery.observability_targets import TargetGenerationState,publish_generation; publish_generation(Path(os.environ["NCDP_TEST_STATE_ROOT"]),state=TargetGenerationState.RETIRED)'

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
  docker inspect "${NCDP_PROMETHEUS_CONTAINER}" >/dev/null

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
  quality_python -c 'from pathlib import Path; from network_change_delivery.observability_targets import TargetGenerationState,publish_generation; publish_generation(Path("/test-state"),state=TargetGenerationState.ACTIVE)'

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
  quality_python -c 'from pathlib import Path; from network_change_delivery.observability_targets import TargetGenerationState,publish_generation; publish_generation(Path("/test-state"),state=TargetGenerationState.RETIRED)'
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
