#!/bin/sh
set -eu

source_root=${NCDP_NETBOX_SOURCE_ROOT:-/Users/netdevops/Projects/personal/network-change-delivery-platform/.local/netbox-docker}
runtime_root=${NCDP_NETBOX_RUNTIME_ROOT:-/Users/netdevops/.local/lib/ncdp/netbox-lab}
service_parent=${NCDP_NETBOX_SERVICE_PARENT:-/Users/netdevops/.local/lib/ncdp}
state_root=${NCDP_NETBOX_STATE_ROOT:-/Users/netdevops/.local/state/ncdp/netbox-lab}
config_root=${NCDP_NETBOX_CONFIG_ROOT:-/Users/netdevops/.config/ncdp/netbox-lab}
plist=/Users/netdevops/Library/LaunchAgents/com.ncdp.netbox-lab.plist
commit=${NCDP_SOURCE_COMMIT:?source commit required}
service_runtime=${service_parent}/netbox-lab-service-${commit}
candidate=${runtime_root}.candidate

[ "$(id -un)" = netdevops ] || { echo "NetBox lifecycle installer user rejected" >&2; exit 2; }
[ ! -e "${runtime_root}" ] || { echo "NetBox lifecycle runtime already exists" >&2; exit 2; }
[ ! -e "${candidate}" ] || { echo "NetBox lifecycle candidate already exists" >&2; exit 2; }
[ ! -e "${service_runtime}" ] || { echo "NetBox lifecycle service runtime already exists" >&2; exit 2; }

umask 077
mkdir -p "${candidate}" "${service_parent}" "${state_root}/logs" "${config_root}"
chmod 0700 "${candidate}" "${service_parent}" "${state_root}" "${state_root}/logs" "${config_root}"
cp "${source_root}/docker-compose.yml" "${candidate}/docker-compose.yml"
cp "${source_root}/docker-compose.override.yml" "${candidate}/docker-compose.override.yml"
cp -R "${source_root}/configuration" "${candidate}/configuration"
cp -R "${source_root}/env" "${candidate}/env"
find "${candidate}" -type d -exec chmod 0700 {} \;
find "${candidate}" -type f -exec chmod 0600 {} \;
uv run python scripts/netbox/write_contract.py "${source_root}" "${candidate}"
mv "${candidate}" "${runtime_root}"

uv venv --python 3.12 "${service_runtime}" >/dev/null
uv build >/dev/null
uv pip install --python "${service_runtime}/bin/python" dist/network_change_delivery-*.whl >/dev/null
printf '%s\n' "${commit}" > "${service_runtime}/source-commit"
chmod 0600 "${service_runtime}/source-commit"

ensure_candidate=${config_root}/.ensure.candidate
cat > "${ensure_candidate}" <<EOF
#!/bin/sh
exec ${service_runtime}/bin/ncdp-netbox-lab-service
EOF
chmod 0700 "${ensure_candidate}"
mv "${ensure_candidate}" "${config_root}/ensure"
for logfile in "${state_root}/logs/service.out.log" "${state_root}/logs/service.err.log"; do
  touch "${logfile}"
  chmod 0600 "${logfile}"
done

cat > "${plist}" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>Label</key><string>com.ncdp.netbox-lab</string>
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
echo "NetBox persistent lifecycle installed"
