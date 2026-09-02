#!/bin/sh
set -eu

state_root=${NCDP_OBSERVABILITY_STATE_ROOT:-/Users/netdevops/.local/state/ncdp/observability}
config_root=${NCDP_OBSERVABILITY_CONFIG_ROOT:-/Users/netdevops/.config/ncdp/observability}
service_parent=${NCDP_OBSERVABILITY_SERVICE_PARENT:-/Users/netdevops/.local/lib/ncdp}
commit=${NCDP_SOURCE_COMMIT:?source commit required}
runtime=${service_parent}/observability-service-${commit}
plist=/Users/netdevops/Library/LaunchAgents/com.ncdp.observability.plist
install_lock=${service_parent}/.observability-install.lock
prometheus='prom/prometheus:v3.14.0@sha256:5ce7540c3c00ef4ab0c9d2c995c6a5b9c421f44b4a115d97a2c7af3b1c21cbb0'
blackbox='prom/blackbox-exporter:v0.27.0@sha256:a50c4c0eda297baa1678cd4dc4712a67fdea713b832d43ce7fcc5f9bea05094d'
grafana='grafana/grafana:12.1.1@sha256:a1701c2180249361737a99a01bc770db39381640e4d631825d38ff4535efa47d'
alertmanager='prom/alertmanager:v0.29.0@sha256:88743b63b3e09ea6e31e140ced5bf45f4a8e82c617c2a963f78841f4995ad1d7'
receiver='python:3.12.13-slim@sha256:2c941e860699f878900b0edc2403613c234d4b32eda3cc9fa7036991a2a63c4a'

[ "$(id -un)" = netdevops ] || { echo "observability installer user rejected" >&2; exit 2; }
[ "${#commit}" -eq 40 ] || { echo "observability source commit rejected" >&2; exit 2; }
case "${commit}" in *[!0-9a-f]*) echo "observability source commit rejected" >&2; exit 2;; esac
[ -n "${NCDP_OBSERVABILITY_NETBOX_TOKEN:-}" ] || { echo "observability NetBox authority missing" >&2; exit 2; }
for name in NCDP_OBSERVABILITY_CML_ADDRESS NCDP_OBSERVABILITY_CML_CACERT NCDP_OBSERVABILITY_CML_USERNAME NCDP_OBSERVABILITY_CML_PASSWORD; do
  eval "value=\${${name}:-}"
  [ -n "${value}" ] || { echo "observability CML authority missing" >&2; exit 2; }
done
for path in "${state_root}" "${config_root}" "${runtime}" "${plist}"; do
  [ ! -e "${path}" ] && [ ! -L "${path}" ] || {
    echo "observability first-install target already exists" >&2
    exit 2
  }
done
case "${state_root}" in /*/observability) ;; *) echo "observability state root rejected" >&2; exit 2;; esac
case "${config_root}" in /*/observability) ;; *) echo "observability config root rejected" >&2; exit 2;; esac
case "${service_parent}" in /*/ncdp) ;; *) echo "observability service parent rejected" >&2; exit 2;; esac

umask 077
mkdir -p "${service_parent}"
chmod 0700 "${service_parent}"
mkdir "${install_lock}" || { echo "observability installation already in progress" >&2; exit 2; }
chmod 0700 "${install_lock}"
install_complete=0
cleanup_incomplete_install() {
  status=$?
  if [ "${install_complete}" -ne 1 ]; then
    rm -f "${plist}"
    rm -rf "${runtime}" "${config_root}" "${state_root}"
  fi
  rmdir "${install_lock}" 2>/dev/null || true
  exit "${status}"
}
trap cleanup_incomplete_install EXIT
trap 'exit 1' HUP INT TERM
for directory in "${state_root}" "${state_root}/runtime" "${state_root}/discovery" "${state_root}/operator" "${state_root}/control" "${state_root}/logs" "${state_root}/prometheus" "${state_root}/grafana" "${state_root}/alertmanager" "${config_root}" "${service_parent}" "${runtime}"; do
  mkdir -p "${directory}"
  chmod 0700 "${directory}"
done
for logfile in "${state_root}/logs/service.out.log" "${state_root}/logs/service.err.log"; do
  touch "${logfile}"
  chmod 0600 "${logfile}"
done

record_image_id() {
  image=$1
  name=$2
  docker image inspect "${image}" --format '{{.Id}} {{.Os}}/{{.Architecture}}' | grep -Eq '^sha256:[0-9a-f]{64} linux/arm64$'
  docker image inspect "${image}" --format '{{.Id}}' > "${config_root}/${name}-image-id"
}
record_image_id "${prometheus}" prometheus
record_image_id "${blackbox}" blackbox
record_image_id "${grafana}" grafana
record_image_id "${alertmanager}" alertmanager
record_image_id "${receiver}" receiver

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
cp infrastructure/observability/prometheus.yml "${config_root}/prometheus.yml"
cp infrastructure/observability/blackbox.yml "${config_root}/blackbox.yml"
printf '%s\n' "${runtime}/compose.yaml" > "${config_root}/compose-path"
printf '%s\n' "${commit}" > "${config_root}/source-commit"
printf '%s' "${NCDP_OBSERVABILITY_NETBOX_TOKEN}" > "${config_root}/netbox-token"
NCDP_OBSERVABILITY_CONFIG_ROOT="${config_root}" "${runtime}/bin/python" -c 'import json, os, pathlib; p=pathlib.Path(os.environ["NCDP_OBSERVABILITY_CONFIG_ROOT"])/"authority.json"; p.write_text(json.dumps({"netbox_url":"http://127.0.0.1:8000","cml_address":os.environ["NCDP_OBSERVABILITY_CML_ADDRESS"],"cml_certificate":os.environ["NCDP_OBSERVABILITY_CML_CACERT"],"cml_username":os.environ["NCDP_OBSERVABILITY_CML_USERNAME"],"cml_password":os.environ["NCDP_OBSERVABILITY_CML_PASSWORD"]},sort_keys=True,separators=(",",":"))+"\n")'
for file in "${runtime}/compose.yaml" "${config_root}/prometheus.yml" "${config_root}/blackbox.yml" "${config_root}/compose-path" "${config_root}/source-commit" "${config_root}/netbox-token" "${config_root}/authority.json" "${config_root}/prometheus-image-id" "${config_root}/blackbox-image-id" "${config_root}/grafana-image-id" "${config_root}/alertmanager-image-id" "${config_root}/receiver-image-id"; do
  chmod 0600 "${file}"
done

NCDP_OBSERVABILITY_STATE_ROOT="${state_root}" "${runtime}/bin/python" -c 'from pathlib import Path; from network_change_delivery.observability_targets import TargetGenerationState,publish_generation; import os; publish_generation(Path(os.environ["NCDP_OBSERVABILITY_STATE_ROOT"]),state=TargetGenerationState.RETIRED)'

cat > "${config_root}/ensure" <<EOF
#!/bin/sh
export NCDP_OBSERVABILITY_RUNTIME_COMMIT=${commit}
exec ${runtime}/bin/ncdp-observability-service
EOF
chmod 0700 "${config_root}/ensure"

cat > "${plist}" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>Label</key><string>com.ncdp.observability</string>
<key>ProgramArguments</key><array><string>${config_root}/ensure</string></array>
<key>RunAtLoad</key><true/><key>StartInterval</key><integer>300</integer>
<key>ThrottleInterval</key><integer>60</integer>
<key>Umask</key><integer>63</integer>
<key>StandardOutPath</key><string>${state_root}/logs/service.out.log</string>
<key>StandardErrorPath</key><string>${state_root}/logs/service.err.log</string>
</dict></plist>
EOF
chmod 0644 "${plist}"
plutil -lint "${plist}" >/dev/null
rmdir "${install_lock}"
install_complete=1
trap - EXIT
trap - HUP INT TERM
echo "observability persistent service installed but not loaded"
