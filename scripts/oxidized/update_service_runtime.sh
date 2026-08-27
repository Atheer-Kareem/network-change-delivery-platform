#!/bin/sh
set -eu

config_root=${NCDP_OXIDIZED_CONFIG_ROOT:-/Users/netdevops/.config/ncdp/oxidized}
service_parent=${NCDP_OXIDIZED_SERVICE_PARENT:-/Users/netdevops/.local/lib/ncdp}
commit=${NCDP_SOURCE_COMMIT:?source commit required}
runtime=${service_parent}/oxidized-service-${commit}

[ "$(id -un)" = netdevops ] || { echo "Oxidized updater user rejected" >&2; exit 2; }
[ ! -e "${runtime}" ] || { echo "Oxidized candidate runtime already exists" >&2; exit 2; }
umask 077
uv venv --python 3.12 "${runtime}" >/dev/null
uv build >/dev/null
uv pip install --python "${runtime}/bin/python" --no-deps dist/network_change_delivery-*.whl >/dev/null
uv pip install --python "${runtime}/bin/python" 'httpx==0.28.1' 'pydantic==2.13.4' 'pyyaml==6.0.3' >/dev/null
printf '%s\n' "${commit}" > "${runtime}/source-commit"
chmod 0600 "${runtime}/source-commit"
"${runtime}/bin/python" -I -c 'import network_change_delivery; print(network_change_delivery.__file__)' >/dev/null
config_candidate=${config_root}/.config.candidate
"${runtime}/bin/python" -I -c 'from pathlib import Path; from network_change_delivery.oxidized_service import render_oxidized_config; Path("/Users/netdevops/.config/ncdp/oxidized/.config.candidate").write_text(render_oxidized_config())'
chmod 0600 "${config_candidate}"
mv "${config_candidate}" "${config_root}/config"
gitconfig_candidate=${config_root}/.gitconfig.candidate
"${runtime}/bin/python" -I -c 'from pathlib import Path; from network_change_delivery.oxidized_service import render_oxidized_git_config; Path("/Users/netdevops/.config/ncdp/oxidized/.gitconfig.candidate").write_text(render_oxidized_git_config())'
chmod 0600 "${gitconfig_candidate}"
mv "${gitconfig_candidate}" "${config_root}/gitconfig"
ensure_candidate=${config_root}/.ensure.candidate
cat > "${ensure_candidate}" <<EOF
#!/bin/sh
exec ${runtime}/bin/ncdp-oxidized-service
EOF
chmod 0700 "${ensure_candidate}"
mv "${ensure_candidate}" "${config_root}/ensure"
echo "Oxidized external runtime updated"
