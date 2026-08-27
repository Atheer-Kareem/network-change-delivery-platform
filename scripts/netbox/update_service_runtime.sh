#!/bin/sh
set -eu

config_root=${NCDP_NETBOX_CONFIG_ROOT:-/Users/netdevops/.config/ncdp/netbox-lab}
service_parent=${NCDP_NETBOX_SERVICE_PARENT:-/Users/netdevops/.local/lib/ncdp}
commit=${NCDP_SOURCE_COMMIT:?source commit required}
runtime=${service_parent}/netbox-lab-service-${commit}

[ "$(id -un)" = netdevops ] || { echo "NetBox updater user rejected" >&2; exit 2; }
[ ! -e "${runtime}" ] || { echo "NetBox candidate runtime already exists" >&2; exit 2; }
umask 077
uv venv --python 3.12 "${runtime}" >/dev/null
uv build >/dev/null
uv pip install --python "${runtime}/bin/python" --no-deps dist/network_change_delivery-*.whl >/dev/null
uv pip install --python "${runtime}/bin/python" 'httpx==0.28.1' 'pydantic==2.13.4' 'pyyaml==6.0.3' >/dev/null
printf '%s\n' "${commit}" > "${runtime}/source-commit"
chmod 0600 "${runtime}/source-commit"
"${runtime}/bin/python" -I -c 'import network_change_delivery; print(network_change_delivery.__file__)' >/dev/null
ensure_candidate=${config_root}/.ensure.candidate
cat > "${ensure_candidate}" <<EOF
#!/bin/sh
exec ${runtime}/bin/ncdp-netbox-lab-service
EOF
chmod 0700 "${ensure_candidate}"
mv "${ensure_candidate}" "${config_root}/ensure"
echo "NetBox external runtime updated"
