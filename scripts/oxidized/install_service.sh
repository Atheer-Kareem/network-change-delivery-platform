#!/bin/sh
set -eu

root=${NCDP_OXIDIZED_RUNTIME_ROOT:-/Users/netdevops/.local/state/ncdp/oxidized}
config_root=${NCDP_OXIDIZED_CONFIG_ROOT:-/Users/netdevops/.config/ncdp/oxidized}
runtime_root=${NCDP_OXIDIZED_SERVICE_RUNTIME:-/Users/netdevops/.local/lib/ncdp/oxidized-service}
image=${NCDP_OXIDIZED_IMAGE:-ncdp-oxidized:10c2}
plist=/Users/netdevops/Library/LaunchAgents/com.ncdp.oxidized.plist

[ "$(id -un)" = netdevops ] || { echo "Oxidized installer user rejected" >&2; exit 2; }
[ -n "${NCDP_OXIDIZED_NETBOX_TOKEN:-}" ] || { echo "Oxidized NetBox authority missing" >&2; exit 2; }

umask 077
for directory in "${root}" "${root}/runtime" "${root}/operator" "${root}/control" "${root}/logs" "${config_root}" "$(dirname "${runtime_root}")"; do
  mkdir -p "${directory}"
  chmod 0700 "${directory}"
done

if [ ! -e "${root}/config-history.git" ]; then
  /usr/bin/git init --bare --quiet "${root}/config-history.git"
fi
chmod 0700 "${root}/config-history.git"
[ "$(/usr/bin/git --git-dir="${root}/config-history.git" rev-list --all --count)" -eq 0 ]
[ -z "$(/usr/bin/git --git-dir="${root}/config-history.git" config --local --name-only --get-regexp '^remote\.' 2>/dev/null || true)" ]

image_id=$(docker image inspect "${image}" --format '{{.Id}}')
case "${image_id}" in sha256:????????????????????????????????????????????????????????????????) ;; *) exit 2 ;; esac

[ ! -e "${runtime_root}" ] || { echo "Oxidized service runtime already exists" >&2; exit 2; }
[ ! -e "${runtime_root}.candidate" ] || { echo "Oxidized service candidate already exists" >&2; exit 2; }
uv venv --python 3.12 "${runtime_root}.candidate" >/dev/null
uv build >/dev/null
uv pip install --python "${runtime_root}.candidate/bin/python" dist/network_change_delivery-*.whl >/dev/null
printf '%s\n' "${NCDP_SOURCE_COMMIT:?source commit required}" > "${runtime_root}.candidate/source-commit"
mv "${runtime_root}.candidate" "${runtime_root}"

printf '%s' "${NCDP_OXIDIZED_NETBOX_TOKEN}" > "${config_root}/netbox-token"
printf '%s\n' "${image_id}" > "${config_root}/image-id"
cat > "${config_root}/authority.json" <<EOF
{"netbox_url":"http://127.0.0.1:8000","openbao_url":"http://127.0.0.1:8200"}
EOF
"${runtime_root}/bin/python" -c 'from pathlib import Path; from network_change_delivery.oxidized_service import render_oxidized_config; Path("/Users/netdevops/.config/ncdp/oxidized/config").write_text(render_oxidized_config())'
chmod 0600 "${config_root}"/*

cat > "${config_root}/ensure" <<EOF
#!/bin/sh
exec ${runtime_root}/bin/ncdp-oxidized-service
EOF
chmod 0700 "${config_root}/ensure"

cat > "${plist}" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>Label</key><string>com.ncdp.oxidized</string>
<key>ProgramArguments</key><array><string>${config_root}/ensure</string></array>
<key>RunAtLoad</key><true/><key>StartInterval</key><integer>300</integer>
<key>ThrottleInterval</key><integer>60</integer>
<key>StandardOutPath</key><string>${root}/logs/service.out.log</string>
<key>StandardErrorPath</key><string>${root}/logs/service.err.log</string>
</dict></plist>
EOF
chmod 0644 "${plist}"
plutil -lint "${plist}" >/dev/null
echo "Oxidized persistent service installed"
