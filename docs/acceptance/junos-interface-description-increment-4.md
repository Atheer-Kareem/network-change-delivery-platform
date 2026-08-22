# Junos interface-description plan-review acceptance — Increment 4

## Scope and credential boundary

Acceptance ran on 2026-08-22 against the synthetic personal-lab device
`edge-junos-01` running Junos `23.2R1.15`. NetBox resolved device identity
`netbox:dcim.device:2` to `192.168.4.20:830` with platform `junos`; `fxp0`
was protected by NetBox metadata.

The temporary operator credential was administratively written to the exact
OpenBao KV-v2 logical path `ncdp/devices/2/ssh`. A metadata-only administrative
read proved current version 1 without reading or printing either value. The
temporary direct credential variables were then unset and proved absent from
the NCDP runtime process. An ephemeral bounded AppRole SecretID was used by
`OpenBaoSecretProvider` for the normal exact-path read. The resulting non-secret
reference was `openbao:kv-v2:ncdp/devices/2/ssh`.

No credential value was printed, logged, persisted in Git, or included in the
plan or this evidence. The static value exists only in the authorized ignored
local OpenBao development fixture.

## Read-only discovery

`NetBoxInventoryProvider`, `OpenBaoSecretProvider`, and `JunosPyEZAdapter` were
used together. The adapter opened a hardened NETCONF session and issued only
structured `get-interface-information terse` and committed `get-configuration`
reads. Real PyEZ acceptance exposed that its configuration filter requires an
XML string or lxml element rather than a standard-library element. The adapter
now serializes its already-typed filter to XML; a regression test covers the
exact unscoped and interface-scoped representations.

All physical interfaces reported by the device follow. `—` means absent or not
reported.

| Interface | Admin | Oper | Committed description | IPv4 addresses | Protected |
| --- | --- | --- | --- | --- | --- |
| `ge-0/0/0` | up | down | — | — | no |
| `lc-0/0/0` | up | up | — | — | no |
| `pfe-0/0/0` | up | up | — | — | no |
| `pfh-0/0/0` | up | up | — | — | no |
| `ge-0/0/1` | up | down | — | — | no |
| `ge-0/0/2` | up | down | — | — | no |
| `ge-0/0/3` | up | down | — | — | no |
| `ge-0/0/4` | up | down | — | — | no |
| `ge-0/0/5` | up | down | — | — | no |
| `ge-0/0/6` | up | down | — | — | no |
| `ge-0/0/7` | up | down | — | — | no |
| `ge-0/0/8` | up | down | — | — | no |
| `ge-0/0/9` | up | down | — | — | no |
| `cbp0` | up | up | — | — | no |
| `demux0` | up | up | — | — | no |
| `dsc` | up | up | — | — | no |
| `em1` | up | up | — | — | no |
| `esi` | up | up | — | — | no |
| `fti0` | up | up | — | — | no |
| `fti1` | up | up | — | — | no |
| `fti2` | up | up | — | — | no |
| `fti3` | up | up | — | — | no |
| `fti4` | up | up | — | — | no |
| `fti5` | up | up | — | — | no |
| `fti6` | up | up | — | — | no |
| `fti7` | up | up | — | — | no |
| `fxp0` | up | up | — | `192.168.4.20/24` | yes |
| `gre` | up | up | — | — | no |
| `ipip` | up | up | — | — | no |
| `irb` | up | up | — | — | no |
| `jsrv` | up | up | — | — | no |
| `lo0` | up | up | — | — | no |
| `lsi` | up | up | — | — | no |
| `mif` | up | up | — | — | no |
| `mtun` | up | up | — | — | no |
| `pimd` | up | up | — | — | no |
| `pime` | up | up | — | — | no |
| `pip0` | up | up | — | — | no |
| `pp0` | up | up | — | — | no |
| `rbeb` | up | up | — | — | no |
| `tap` | up | up | — | — | no |
| `vtep` | up | up | — | — | no |

The plausible safe candidates were `ge-0/0/0` through `ge-0/0/9`: each is a
front-panel physical port, unprotected, has no committed description or IPv4
address, and is operationally down. `ge-0/0/1` was selected as the first unused
non-management candidate. The exact NetBox object was already present when the
idempotent create boundary ran; it was the sole exact match with the expected
type and stable identity `netbox:dcim.interface:4`. No other interface object
was created or changed.

## Immutable plan review

The normal command path equivalent to `ncdp plan --netbox --openbao` generated
one ignored local plan for `ge-0/0/1` with desired description
`managed-by-network-change-delivery-platform`. The plan binds:

- NetBox device `netbox:dcim.device:2` and interface
  `netbox:dcim.interface:4`;
- OpenBao reference `openbao:kv-v2:ncdp/devices/2/ssh`;
- observed hostname `edge-junos-01`, existing unprotected interface, and absent
  current description;
- deterministic XML merge for only `ge-0/0/1`;
- exclusive candidate mode, `junos_commit_confirmed`, fixed five-minute
  timeout, and `confirm_previous_commit`.

The stored canonical plan digest is
`sha256:193419efb2f332d4ef99648047cffd38dfb224d45406f30388735eb7f5fd0023`.
An independent JSON canonicalization and SHA-256 calculation produced the exact
same digest.

The plan was not executed. `Config.load`, commit-check, commit,
commit-confirmed, confirmation, rollback, and `ncdp deploy` were not invoked.
Device configuration writes were exactly zero. The plan remains stopped for
human review and separate exact-digest approval.
