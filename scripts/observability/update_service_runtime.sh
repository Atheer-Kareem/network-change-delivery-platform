#!/bin/sh
set -eu

config_root=${NCDP_OBSERVABILITY_CONFIG_ROOT:-/Users/netdevops/.config/ncdp/observability}
service_parent=${NCDP_OBSERVABILITY_SERVICE_PARENT:-/Users/netdevops/.local/lib/ncdp}
commit=${NCDP_SOURCE_COMMIT:?source commit required}
runtime=${service_parent}/observability-service-${commit}

[ "$(id -un)" = netdevops ] || { echo "observability updater user rejected" >&2; exit 2; }
[ ! -e "${runtime}" ] || { echo "observability candidate runtime already exists" >&2; exit 2; }
umask 077
mkdir -p "${runtime}"
chmod 0700 "${runtime}"
uv venv --python 3.12 "${runtime}" >/dev/null
uv build >/dev/null
uv pip install --python "${runtime}/bin/python" --no-deps dist/network_change_delivery-*.whl >/dev/null
uv pip install --python "${runtime}/bin/python" 'httpx==0.28.1' 'pydantic==2.13.4' 'pyyaml==6.0.3' >/dev/null
cp infrastructure/observability/compose.yaml "${runtime}/compose.yaml"
cp infrastructure/observability/prometheus.yml "${config_root}/.prometheus.yml.candidate"
cp infrastructure/observability/blackbox.yml "${config_root}/.blackbox.yml.candidate"
printf '%s\n' "${runtime}/compose.yaml" > "${config_root}/.compose-path.candidate"
printf '%s\n' "${commit}" > "${config_root}/.source-commit.candidate"
for file in "${runtime}/compose.yaml" "${config_root}/.prometheus.yml.candidate" "${config_root}/.blackbox.yml.candidate" "${config_root}/.compose-path.candidate" "${config_root}/.source-commit.candidate"; do chmod 0600 "${file}"; done
mv "${config_root}/.prometheus.yml.candidate" "${config_root}/prometheus.yml"
mv "${config_root}/.blackbox.yml.candidate" "${config_root}/blackbox.yml"
mv "${config_root}/.compose-path.candidate" "${config_root}/compose-path"
mv "${config_root}/.source-commit.candidate" "${config_root}/source-commit"
cat > "${config_root}/.ensure.candidate" <<EOF
#!/bin/sh
exec ${runtime}/bin/ncdp-observability-service
EOF
chmod 0700 "${config_root}/.ensure.candidate"
mv "${config_root}/.ensure.candidate" "${config_root}/ensure"
echo "observability external runtime updated"
