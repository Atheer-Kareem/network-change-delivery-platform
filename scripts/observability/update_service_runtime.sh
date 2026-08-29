#!/bin/sh
set -eu

config_root=${NCDP_OBSERVABILITY_CONFIG_ROOT:-/Users/netdevops/.config/ncdp/observability}
state_root=${NCDP_OBSERVABILITY_STATE_ROOT:-/Users/netdevops/.local/state/ncdp/observability}
service_parent=${NCDP_OBSERVABILITY_SERVICE_PARENT:-/Users/netdevops/.local/lib/ncdp}
commit=${NCDP_SOURCE_COMMIT:?source commit required}
runtime=${service_parent}/observability-service-${commit}

[ "$(id -un)" = netdevops ] || { echo "observability updater user rejected" >&2; exit 2; }
[ "${#commit}" -eq 40 ] || { echo "observability source commit rejected" >&2; exit 2; }
case "${commit}" in *[!0-9a-f]*) echo "observability source commit rejected" >&2; exit 2;; esac
[ ! -e "${runtime}" ] || { echo "observability candidate runtime already exists" >&2; exit 2; }
umask 077
mkdir -p "${runtime}"
chmod 0700 "${runtime}"
uv venv --python 3.12 "${runtime}" >/dev/null
uv build >/dev/null
uv pip install --python "${runtime}/bin/python" --no-deps dist/network_change_delivery-*.whl >/dev/null
uv pip install --python "${runtime}/bin/python" 'httpx==0.28.1' 'pydantic==2.13.4' 'pyyaml==6.0.3' >/dev/null
cp infrastructure/observability/compose.yaml "${runtime}/compose.yaml"
if [ -f infrastructure/observability/rules/11b-alerts.yml ]; then
  mkdir -p "${runtime}/rules" "${runtime}/alertmanager" "${runtime}/grafana/provisioning/datasources" "${runtime}/grafana/provisioning/dashboards" "${runtime}/grafana/dashboards" "${runtime}/receiver"
  cp infrastructure/observability/rules/11b-alerts.yml "${runtime}/rules/11b-alerts.yml"
  cp infrastructure/observability/alertmanager.yml "${runtime}/alertmanager/alertmanager.yml"
  cp infrastructure/observability/grafana/provisioning/datasources/prometheus.yml "${runtime}/grafana/provisioning/datasources/prometheus.yml"
  cp infrastructure/observability/grafana/provisioning/dashboards/dashboards.yml "${runtime}/grafana/provisioning/dashboards/dashboards.yml"
  cp infrastructure/observability/grafana/dashboards/ncdp-management-reachability.json "${runtime}/grafana/dashboards/ncdp-management-reachability.json"
  cp scripts/observability/demo_receiver.py "${runtime}/receiver/demo_receiver.py"
fi
cp infrastructure/observability/prometheus.yml "${config_root}/.prometheus.yml.candidate"
cp infrastructure/observability/blackbox.yml "${config_root}/.blackbox.yml.candidate"
printf '%s\n' "${runtime}/compose.yaml" > "${config_root}/.compose-path.candidate"
printf '%s\n' "${commit}" > "${config_root}/.source-commit.candidate"
for file in "${runtime}/compose.yaml" "${config_root}/.prometheus.yml.candidate" "${config_root}/.blackbox.yml.candidate" "${config_root}/.compose-path.candidate" "${config_root}/.source-commit.candidate"; do chmod 0600 "${file}"; done
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
