#!/bin/sh
set -eu

umask 077
private_root=/run/ncdp-agent
users_file=${private_root}/agent-users.conf
config_file=${private_root}/snmpd.conf

for private_item in "${private_root}" "${users_file}" "${config_file}"; do
  if [ -L "${private_item}" ]; then
    echo "synthetic SNMP private path rejected" >&2
    exit 2
  fi
done
[ -d "${private_root}" ]
[ -f "${users_file}" ]
[ -f "${config_file}" ]
[ "$(stat -c '%a' "${private_root}")" = 700 ]
[ "$(stat -c '%a' "${users_file}")" = 600 ]
[ "$(stat -c '%a' "${config_file}")" = 600 ]
[ "$(stat -c '%h' "${users_file}")" = 1 ]
[ "$(stat -c '%h' "${config_file}")" = 1 ]

cp "${users_file}" /var/lib/snmp/snmpd.conf
chmod 0600 /var/lib/snmp/snmpd.conf
exec /usr/sbin/snmpd -f -LS0-3d -C -c "${config_file},/var/lib/snmp/snmpd.conf"
