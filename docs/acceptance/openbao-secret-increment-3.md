# OpenBao secret acceptance — Increment 3

## Local service and administrative controls

Acceptance ran on 2026-08-22 against OpenBao 2.6.2 using the official image
`docker.io/openbao/openbao:2.6.2`. Its resolved multi-platform digest was
`sha256:11fd73a2102cda9c55d5d881a8c3210303146a7ec1e8ac76f526e175c6d24641`;
the accepted `linux/arm64` manifest was
`sha256:c3c4bcd0ecf54fd5256881e85f3c0dba97d540e024da3c18504e5f1fce1e981a`.

The service was a non-production development-mode personal-lab fixture held in
ignored `.local/openbao/` state and published only on `127.0.0.1:8200`. Its
administrative token was used only for setup/inspection and was not supplied to
NCDP. Bootstrap material and device credential values remained ignored and
permission restricted.

Administrative inspection proved:

- AppRole was enabled and a dedicated `ncdp-personal-lab` role was used;
- `bind_secret_id = true`, `secret_id_ttl = 30m`, and `secret_id_num_uses = 10`;
- `token_ttl = 5m`, `token_max_ttl = 5m`, and `token_num_uses = 1`;
- policy `ncdp-device-1` granted only `read` on
  `ncdp/data/devices/1/ssh`;
- KV-v2 mount `ncdp/` held the current static lab device credential at the
  exact logical path `devices/1/ssh`.

No broad list, write, delete, sys, auth-management, or other device-path
capability was granted to the NCDP role.

## Combined read-only acceptance

The run used `NetBoxInventoryProvider` and `OpenBaoSecretProvider` together.
`NCDP_DEVICE_USERNAME` and `NCDP_DEVICE_PASSWORD` were explicitly removed from
the NCDP process environment before invocation.

- NetBox device identity: `netbox:dcim.device:1`;
- requested interface identity: `netbox:dcim.interface:2`;
- protected metadata: `GigabitEthernet1` protected, `GigabitEthernet2` unprotected;
- credential source: `openbao`;
- credential reference: `openbao:kv-v2:ncdp/devices/1/ssh`;
- observed hostname: `core-02`;
- observed IOS XE version: `17.18.02`;
- observed Gi2 description: `managed-by-network-change-delivery-platform`.

AppRole authentication issued an acceptable short-lived token, and that token
was consumed by the one exact KV-v2 GET. Ansible then performed read-only live
collection. `ncdp plan --netbox --openbao` reported the safe credential
provenance and `interface is already compliant; no deployable artifact produced`.
No plan file was produced.

`ncdp deploy` was not run. The executor and `ios_config` were not invoked, no
startup-config save occurred, and device writes were exactly zero. Normal NCDP
execution performed no NetBox or OpenBao secret writes. No secret value appeared
in Git, the diff, plans, evidence, or this record.

## Security claim and limitations

Acceptance proves AppRole machine authentication, short-lived narrowly scoped
OpenBao tokens, exact-path KV-v2 retrieval, and removal of direct device
credentials from the primary NCDP environment path. The underlying IOS XE
credential remains static. This does not prove dynamic or short-lived Cisco
credentials, per-command authorization, credential rotation, or production-grade
Buildkite JWT/OIDC federation.
