# Detour B3-3 profiled OpenBao onboarding acceptance

## Scope and pipeline safety

Detour B3-3 changes only local OpenBao credential/read authority and the
repository pipeline definition. Persistent CML nodes, device configuration,
host trust, NetBox, Terraform state, protected device authority, SNMP authority,
and Buildkite external settings were not changed.

The active `cml-staging` step is commented out with a direct B3-5 restoration
marker. The complete protected-delivery group is commented out with it; its
promotion dependency was not bypassed. Quality validation, Terraform static
validation, pipeline contracts, and PR Batfish candidate assurance remain
active. Staging scripts, Terraform, drivers, tests, and historical acceptance
evidence remain present.

## Applied OpenBao authority

The local OpenBao instance remained initialized, unsealed, active, loopback
published, and backed by its existing persistent file storage. The `ncdp/`
mount remained KV-v2.

The bounded operator configuration created these paths with independently
generated passwords held only by OpenBao:

- `ncdp/devices/8/ssh` for `netbox:dcim.device:8`;
- `ncdp/devices/9/ssh` for `netbox:dcim.device:9`.

Both schemas are exactly `username` and `password`, with username `netdevops`.
Devices 1/2 remained at secret version 1 and were compared before and after the
operator run; their values were unchanged. A second B3-3 configuration
pass reused devices 8/9 with no password rotation.

The existing `ncdp-personal-lab` AppRole retains its 300-second token TTL,
300-second maximum TTL, and one-use token behavior. Its existing policy now has
only exact read paths for devices 1, 2, 8, and 9. It grants no wildcard, list,
write, delete, auth-management, or sys-management capability.

A fresh bounded SecretID exercised the normal `OpenBaoSecretProvider` path and
was destroyed after acceptance. Secret-free outcomes were:

| Stable identity | Credential reference | Result |
|---|---|---|
| `netbox:dcim.device:1` | `openbao:kv-v2:ncdp/devices/1/ssh` | PASS |
| `netbox:dcim.device:2` | `openbao:kv-v2:ncdp/devices/2/ssh` | PASS |
| `netbox:dcim.device:8` | `openbao:kv-v2:ncdp/devices/8/ssh` | PASS |
| `netbox:dcim.device:9` | `openbao:kv-v2:ncdp/devices/9/ssh` | PASS |
| `netbox:dcim.device:10` | none admitted | FAIL CLOSED |

Unauthenticated reads remained HTTP 403.

## Staging and unchanged authorities

These new exact staging capabilities were configured and verified twice:

- policy `ncdp-buildkite-staging-device-8-read` and role
  `ncdp-buildkite-staging-device-8`;
- policy `ncdp-buildkite-staging-device-9-read` and role
  `ncdp-buildkite-staging-device-9`.

They preserve the existing staging audience, immutable pipeline subject,
`cml-staging` step binding, claim mappings, 300-second TTL, no-default-policy,
and one-use behavior. Each role carries only its matching exact SSH-read policy.

Protected deployment roles remained exactly devices 1/2. SNMP provisioning
roles remained exactly devices 1/2. No device 8/9 protected-deploy or SNMP role,
policy, or secret was created.

## Repository validation

Focused OpenBao, profile-inventory, staging, pipeline, Terraform, and v1
compatibility coverage passed 172 tests. The complete host suite passed 1,528
tests with 3 environment-dependent Batfish tests skipped. The pinned Docker
quality image passed 1,466 tests with 65 environment-dependent tests skipped,
plus Ruff, Ansible lint, and package build. Frozen dependency sync, CLI smoke,
Buildkite dry-run parsing with secret/parse-warning rejection, Markdown links,
`git diff --check`, the runtime image build, and runtime CLI smoke all passed.
