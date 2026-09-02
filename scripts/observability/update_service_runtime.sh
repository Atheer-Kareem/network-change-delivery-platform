#!/bin/sh
set -eu

config_root=${NCDP_OBSERVABILITY_CONFIG_ROOT:-/Users/netdevops/.config/ncdp/observability}
state_root=${NCDP_OBSERVABILITY_STATE_ROOT:-/Users/netdevops/.local/state/ncdp/observability}
service_parent=${NCDP_OBSERVABILITY_SERVICE_PARENT:-/Users/netdevops/.local/lib/ncdp}
commit=${NCDP_SOURCE_COMMIT:?source commit required}
runtime=${service_parent}/observability-service-${commit}
prometheus='prom/prometheus:v3.14.0@sha256:5ce7540c3c00ef4ab0c9d2c995c6a5b9c421f44b4a115d97a2c7af3b1c21cbb0'
blackbox='prom/blackbox-exporter:v0.27.0@sha256:a50c4c0eda297baa1678cd4dc4712a67fdea713b832d43ce7fcc5f9bea05094d'
grafana='grafana/grafana:12.1.1@sha256:a1701c2180249361737a99a01bc770db39381640e4d631825d38ff4535efa47d'
alertmanager='prom/alertmanager:v0.29.0@sha256:88743b63b3e09ea6e31e140ced5bf45f4a8e82c617c2a963f78841f4995ad1d7'
receiver='python:3.12.13-slim@sha256:2c941e860699f878900b0edc2403613c234d4b32eda3cc9fa7036991a2a63c4a'

[ "$(id -un)" = netdevops ] || { echo "observability updater user rejected" >&2; exit 2; }
[ "${#commit}" -eq 40 ] || { echo "observability source commit rejected" >&2; exit 2; }
case "${commit}" in *[!0-9a-f]*) echo "observability source commit rejected" >&2; exit 2;; esac
[ ! -e "${runtime}" ] || { echo "observability candidate runtime already exists" >&2; exit 2; }
umask 077
for directory in "${state_root}/grafana" "${state_root}/alertmanager"; do
  [ ! -L "${directory}" ] && { [ ! -e "${directory}" ] || [ -d "${directory}" ]; } || {
    echo "observability writable state rejected" >&2
    exit 2
  }
  mkdir -p "${directory}"
  chmod 0700 "${directory}"
done
mkdir -p "${runtime}"
chmod 0700 "${runtime}"
uv venv --python 3.12 "${runtime}" >/dev/null
uv build >/dev/null
uv pip install --python "${runtime}/bin/python" --no-deps dist/network_change_delivery-*.whl >/dev/null
uv pip install --python "${runtime}/bin/python" 'httpx==0.28.1' 'pydantic==2.13.4' 'pyyaml==6.0.3' >/dev/null
cp infrastructure/observability/compose.yaml "${runtime}/compose.yaml"
if [ -f infrastructure/observability/rules/management-reachability-alerts.yml ]; then
  mkdir -p "${runtime}/rules" "${runtime}/alertmanager" "${runtime}/grafana/provisioning/datasources" "${runtime}/grafana/provisioning/dashboards" "${runtime}/grafana/dashboards" "${runtime}/receiver"
  cp infrastructure/observability/rules/management-reachability-alerts.yml "${runtime}/rules/management-reachability-alerts.yml"
  cp infrastructure/observability/alertmanager.yml "${runtime}/alertmanager/alertmanager.yml"
  cp infrastructure/observability/grafana/provisioning/datasources/prometheus.yml "${runtime}/grafana/provisioning/datasources/prometheus.yml"
  cp infrastructure/observability/grafana/provisioning/dashboards/dashboards.yml "${runtime}/grafana/provisioning/dashboards/dashboards.yml"
  cp infrastructure/observability/grafana/dashboards/ncdp-management-reachability.json "${runtime}/grafana/dashboards/ncdp-management-reachability.json"
  cp scripts/observability/demo_receiver.py "${runtime}/receiver/demo_receiver.py"
  for directory in "${runtime}/rules" "${runtime}/alertmanager" "${runtime}/grafana" "${runtime}/grafana/provisioning" "${runtime}/grafana/provisioning/datasources" "${runtime}/grafana/provisioning/dashboards" "${runtime}/grafana/dashboards" "${runtime}/receiver"; do chmod 0700 "${directory}"; done
  for file in "${runtime}/rules/management-reachability-alerts.yml" "${runtime}/alertmanager/alertmanager.yml" "${runtime}/grafana/provisioning/datasources/prometheus.yml" "${runtime}/grafana/provisioning/dashboards/dashboards.yml" "${runtime}/grafana/dashboards/ncdp-management-reachability.json" "${runtime}/receiver/demo_receiver.py"; do chmod 0600 "${file}"; done
fi
stage_image_id() {
  image=$1
  name=$2
  docker image inspect "${image}" --format '{{.Id}} {{.Os}}/{{.Architecture}}' | grep -Eq '^sha256:[0-9a-f]{64} linux/arm64$'
  docker image inspect "${image}" --format '{{.Id}}' > "${config_root}/.${name}-image-id.candidate"
}
stage_image_id "${prometheus}" prometheus
stage_image_id "${blackbox}" blackbox
stage_image_id "${grafana}" grafana
stage_image_id "${alertmanager}" alertmanager
stage_image_id "${receiver}" receiver
cp infrastructure/observability/prometheus.yml "${config_root}/.prometheus.yml.candidate"
cp infrastructure/observability/blackbox.yml "${config_root}/.blackbox.yml.candidate"
printf '%s\n' "${runtime}/compose.yaml" > "${config_root}/.compose-path.candidate"
printf '%s\n' "${commit}" > "${config_root}/.source-commit.candidate"
for file in "${runtime}/compose.yaml" "${config_root}/.prometheus.yml.candidate" "${config_root}/.blackbox.yml.candidate" "${config_root}/.compose-path.candidate" "${config_root}/.source-commit.candidate" "${config_root}/.prometheus-image-id.candidate" "${config_root}/.blackbox-image-id.candidate" "${config_root}/.grafana-image-id.candidate" "${config_root}/.alertmanager-image-id.candidate" "${config_root}/.receiver-image-id.candidate"; do chmod 0600 "${file}"; done
guard=${config_root}/runtime-update-in-progress
lock=${config_root}/runtime-transition.lock
[ ! -e "${lock}" ] || { echo "observability runtime transition ambiguous" >&2; exit 2; }
mkdir "${lock}"
chmod 0700 "${lock}"
[ ! -e "${guard}" ] || { echo "observability runtime update already ambiguous" >&2; exit 2; }
printf '%s\n' "${commit}" > "${guard}"
chmod 0600 "${guard}"
rm -f "${state_root}/runtime/observability-ready.json"
mv "${config_root}/.prometheus.yml.candidate" "${config_root}/prometheus.yml"
mv "${config_root}/.blackbox.yml.candidate" "${config_root}/blackbox.yml"
mv "${config_root}/.prometheus-image-id.candidate" "${config_root}/prometheus-image-id"
mv "${config_root}/.blackbox-image-id.candidate" "${config_root}/blackbox-image-id"
mv "${config_root}/.grafana-image-id.candidate" "${config_root}/grafana-image-id"
mv "${config_root}/.alertmanager-image-id.candidate" "${config_root}/alertmanager-image-id"
mv "${config_root}/.receiver-image-id.candidate" "${config_root}/receiver-image-id"
mv "${config_root}/.compose-path.candidate" "${config_root}/compose-path"
mv "${config_root}/.source-commit.candidate" "${config_root}/source-commit"
cat > "${config_root}/.ensure.candidate" <<EOF
#!/bin/sh
export NCDP_OBSERVABILITY_RUNTIME_COMMIT=${commit}
exec ${runtime}/bin/ncdp-observability-service
EOF
chmod 0700 "${config_root}/.ensure.candidate"
mv "${config_root}/.ensure.candidate" "${config_root}/ensure"
rm "${guard}"
rmdir "${lock}"
echo "observability external runtime updated"
