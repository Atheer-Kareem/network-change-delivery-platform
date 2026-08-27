#!/bin/sh
set -eu

state_root=${NCDP_OBSERVABILITY_STATE_ROOT:-/Users/netdevops/.local/state/ncdp/observability}
config_root=${NCDP_OBSERVABILITY_CONFIG_ROOT:-/Users/netdevops/.config/ncdp/observability}
service_parent=${NCDP_OBSERVABILITY_SERVICE_PARENT:-/Users/netdevops/.local/lib/ncdp}
commit=${NCDP_SOURCE_COMMIT:?source commit required}
runtime=${service_parent}/observability-service-${commit}
plist=/Users/netdevops/Library/LaunchAgents/com.ncdp.observability.plist
prometheus='prom/prometheus:v3.14.0@sha256:5ce7540c3c00ef4ab0c9d2c995c6a5b9c421f44b4a115d97a2c7af3b1c21cbb0'
blackbox='prom/blackbox-exporter:v0.27.0@sha256:a50c4c0eda297baa1678cd4dc4712a67fdea713b832d43ce7fcc5f9bea05094d'

[ "$(id -un)" = netdevops ] || { echo "observability installer user rejected" >&2; exit 2; }
[ -n "${NCDP_OBSERVABILITY_NETBOX_TOKEN:-}" ] || { echo "observability NetBox authority missing" >&2; exit 2; }
for name in NCDP_OBSERVABILITY_CML_ADDRESS NCDP_OBSERVABILITY_CML_CACERT NCDP_OBSERVABILITY_CML_USERNAME NCDP_OBSERVABILITY_CML_PASSWORD; do
  eval "value=\${${name}:-}"
  [ -n "${value}" ] || { echo "observability CML authority missing" >&2; exit 2; }
done
[ ! -e "${runtime}" ] || { echo "observability service runtime already exists" >&2; exit 2; }

umask 077
for directory in "${state_root}" "${state_root}/runtime" "${state_root}/discovery" "${state_root}/operator" "${state_root}/control" "${state_root}/logs" "${state_root}/prometheus" "${config_root}" "${service_parent}" "${runtime}"; do
  mkdir -p "${directory}"
  chmod 0700 "${directory}"
done
for logfile in "${state_root}/logs/service.out.log" "${state_root}/logs/service.err.log"; do
  touch "${logfile}"
  chmod 0600 "${logfile}"
done

docker image inspect "${prometheus}" --format '{{.Id}} {{.Os}}/{{.Architecture}}' | grep -Eq '^sha256:[0-9a-f]{64} linux/arm64$'
docker image inspect "${blackbox}" --format '{{.Id}} {{.Os}}/{{.Architecture}}' | grep -Eq '^sha256:[0-9a-f]{64} linux/arm64$'
docker image inspect "${prometheus}" --format '{{.Id}}' > "${config_root}/prometheus-image-id"
docker image inspect "${blackbox}" --format '{{.Id}}' > "${config_root}/blackbox-image-id"

uv venv --python 3.12 "${runtime}" >/dev/null
uv build >/dev/null
uv pip install --python "${runtime}/bin/python" --no-deps dist/network_change_delivery-*.whl >/dev/null
uv pip install --python "${runtime}/bin/python" 'httpx==0.28.1' 'pydantic==2.13.4' 'pyyaml==6.0.3' >/dev/null
cp infrastructure/observability/compose.yaml "${runtime}/compose.yaml"
cp infrastructure/observability/prometheus.yml "${config_root}/prometheus.yml"
cp infrastructure/observability/blackbox.yml "${config_root}/blackbox.yml"
printf '%s\n' "${runtime}/compose.yaml" > "${config_root}/compose-path"
printf '%s\n' "${commit}" > "${config_root}/source-commit"
printf '%s' "${NCDP_OBSERVABILITY_NETBOX_TOKEN}" > "${config_root}/netbox-token"
NCDP_OBSERVABILITY_CONFIG_ROOT="${config_root}" python -c 'import json, os, pathlib; p=pathlib.Path(os.environ["NCDP_OBSERVABILITY_CONFIG_ROOT"])/"authority.json"; p.write_text(json.dumps({"netbox_url":"http://127.0.0.1:8000","cml_address":os.environ["NCDP_OBSERVABILITY_CML_ADDRESS"],"cml_certificate":os.environ["NCDP_OBSERVABILITY_CML_CACERT"],"cml_username":os.environ["NCDP_OBSERVABILITY_CML_USERNAME"],"cml_password":os.environ["NCDP_OBSERVABILITY_CML_PASSWORD"]},sort_keys=True,separators=(",",":"))+"\n")'
for file in "${runtime}/compose.yaml" "${config_root}/prometheus.yml" "${config_root}/blackbox.yml" "${config_root}/compose-path" "${config_root}/source-commit" "${config_root}/netbox-token" "${config_root}/authority.json" "${config_root}/prometheus-image-id" "${config_root}/blackbox-image-id"; do
  chmod 0600 "${file}"
done

NCDP_OBSERVABILITY_STATE_ROOT="${state_root}" "${runtime}/bin/python" -c 'from pathlib import Path; from network_change_delivery.observability_targets import TargetGenerationState,publish_generation; import os; publish_generation(Path(os.environ["NCDP_OBSERVABILITY_STATE_ROOT"]),state=TargetGenerationState.RETIRED)'

cat > "${config_root}/ensure" <<EOF
#!/bin/sh
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
echo "observability persistent service installed but not loaded"
