# Increment 8A Terraform/CML discovery acceptance

Status: discovery complete; architecture acceptance completes when this change
is reviewed and merged.

## Discovery method and safety

The operator supplied an ephemeral CML address and JWT. Discovery used HTTPS
against only that controller, authenticated first through the harmless
`/api/v0/authok` endpoint, and then performed read-only CML API inspection. The
JWT was consumed from the process environment and was neither printed nor
persisted. No Terraform command or CML lifecycle operation ran. NetBox, OpenBao,
Buildkite runtime systems, and network devices were not accessed.

The controller uses a self-signed certificate. Discovery established encrypted
reachability to the exact supplied endpoint, but future Terraform access must
use an operator-controlled trusted PEM through `CML2_CACERT`; disabling
verification is not accepted.

## Controller and capacity evidence

| Property | Accepted observation |
| --- | --- |
| Version | `2.10.0+build.13` |
| Ready | `true` |
| Health | valid |
| License | licensed and in compliance |
| Tier | CML Personal |
| Licensed node capacity | 20 |
| Compute | single controller/compute, `cml-lab01` |
| KVM | available |
| CPU | 14 threads total; 6 allocated; approximately 8 unallocated |
| RAM | 32,929,226,752 bytes total; 16,198,647,808 bytes free |
| Disk | 973,288,353,792 bytes total; 911,286,267,904 bytes free |
| Current runtime | 4 running nodes; 9 compute-counted nodes plus one external connector |

An equivalent NCDP router set requires 6 vCPUs and 14,336 MiB RAM: two CAT8000V
nodes at 1 vCPU and 4096 MiB each, plus one vJunos Router at 4 vCPUs and
6144 MiB. A separate twin fits, but running both full router sets leaves only
approximately 1.1–1.5 GiB RAM margin. Increment 8 does not require both to stay
running. Full lifecycle/reset acceptance keeps only one heavy set running unless
new capacity evidence explicitly changes the rule.

## Accepted lab inventory

- Title: `Lab at Wed 21:44 PM`
- UUID: `09605569-0468-4fc4-8684-beb5a1342b9c`
- State: `STARTED`
- Node count: 10
- Link count: 11
- Autostart: disabled
- Node staging: disabled

Safe node metadata:

| Canvas label | UUID | Node definition | State | Canvas x, y |
| --- | --- | --- | --- | --- |
| `ext-conn-0` | `9155d0a4-e72b-4ab9-9f62-8d485de3ace0` | `external_connector` | `BOOTED` | 120, -280 |
| `core01` | `5617e4bf-e102-4436-88be-1a4729acb1b7` | `iosv` | `STOPPED` | -160, -120 |
| `br01-rtr01` | `0537e37e-4458-428e-a0cd-217aa0462ba2` | `iosv` | `STOPPED` | 0, -80 |
| `br01-sw01` | `234c7376-8fa3-40ad-abfe-50c244338d46` | `iosvl2` | `STOPPED` | 200, -40 |
| `unmanaged-switch-0` | `e4542ca6-6fa9-46c6-bc95-6b437a8f270a` | `unmanaged_switch` | `BOOTED` | 80, -200 |
| `alpine-0` | `fff7d10a-ace2-4c62-96e0-97935ada102c` | `alpine` | `STOPPED` | 440, 0 |
| `alpine-1` | `f7a364b9-3c11-4d93-86ff-d228b08f2c1b` | `alpine` | `STOPPED` | 560, -80 |
| `cat8000v-0` | `8c193771-d96a-4b0c-b8d6-9ce68333079b` | `cat8000v` | `BOOTED` | -200, -320 |
| `vjunos-router-0` | `2644ab1e-cd24-4590-a165-8514681b2417` | `vjunos-router` | `BOOTED` | 400, -240 |
| `cat8000v-1` | `ff1e83b9-35b5-436e-ba16-320146c297fa` | `cat8000v` | `BOOTED` | -360, -200 |

Prior accepted live NCDP evidence correlates `cat8000v-0` to `core-02`,
`vjunos-router-0` to `edge-junos-01`, and `cat8000v-1` to `core-03`. Stored CML
configurations contain placeholder hostnames and are not evidence of current
runtime identity.

Relevant realization metadata:

| Platform | Node definition | Image definition | Image label | CPU | RAM |
| --- | --- | --- | --- | --- | --- |
| Cisco IOS XE | `cat8000v` | `cat8000v-17-18-02` | Cat 8000v 17.18.02 | 1 vCPU | 4096 MiB |
| Junos | `vjunos-router` | `vjunos-router-23-2r1-15` | vJunos Router 23.2R1.15 | 4 vCPUs | 6144 MiB |

CAT8000V slots 0–3 are `GigabitEthernet1` through `GigabitEthernet4`. vJunos
slots 0–3 are `fxp0`, `ge-0/0/0`, `ge-0/0/1`, and `ge-0/0/2`. The management
connections are `GigabitEthernet1` for both Cisco nodes and `fxp0` for Junos.

## Normalized observed CML links

Endpoints are lexically normalized within each pair and the list is sorted:

```text
alpine-0:eth0 -- br01-sw01:GigabitEthernet0/2
alpine-1:eth0 -- br01-sw01:GigabitEthernet0/3
br01-rtr01:GigabitEthernet0/0 -- unmanaged-switch-0:port1
br01-rtr01:GigabitEthernet0/1 -- core01:GigabitEthernet0/1
br01-rtr01:GigabitEthernet0/2 -- br01-sw01:GigabitEthernet0/1
br01-sw01:GigabitEthernet0/0 -- unmanaged-switch-0:port2
cat8000v-0:GigabitEthernet1 -- unmanaged-switch-0:port4
cat8000v-1:GigabitEthernet1 -- unmanaged-switch-0:port6
core01:GigabitEthernet0/0 -- unmanaged-switch-0:port0
ext-conn-0:port -- unmanaged-switch-0:port3
unmanaged-switch-0:port5 -- vjunos-router-0:fxp0
```

All three NCDP nodes connect only through the existing shared management fabric.
There are no CML data-plane links among them, so the accepted lab is not an exact
data-plane twin and no future CML data-plane topology may be inferred from these
links.

The sanitized plan-bound Batfish baseline separately models
`core-02:GigabitEthernet1` to `edge-junos-01:ge-0/0/0`, then
`edge-junos-01:ge-0/0/1` to `core-03:GigabitEthernet1`. That is a synthetic
behavioral-assurance scenario, not observed CML wiring. Because Cisco
`GigabitEthernet1` is management in live CML, Terraform must select explicit
non-management interfaces under a new scenario contract.

## Connector and stored-configuration evidence

The external connector canvas label is `ext-conn-0`; its discovered UI selector
is `System Bridge`. The inspected raw node and interface representations did not
expose the backing Linux device name. It must later be uniquely resolved from
the provider `cml2_connector` data source, never guessed.

Stored configurations were hashed in memory without reproducing their contents:

| Node | Stored name | Bytes | SHA-256 | Recognized secret-bearing patterns |
| --- | --- | ---: | --- | --- |
| `ext-conn-0` | `default` | 13 | `b3cd30ae4a3587b157e5e9f25121b941cf8226d021a2456c15dc20d20a5c156f` | none |
| `cat8000v-0` | `iosxe_config.txt` | 60 | `6af0386442a0937d7371487cea564a7473d7bafcb7bdc11ccb49eb65479ebd23` | none |
| `vjunos-router-0` | `config/juniper.conf` | 823 | `78d1ab65c05a0c2e2fb0a7a907c67d5d56df68cd376a24f6595e0e55ce7ef70d` | none |
| `cat8000v-1` | `iosxe_config.txt` | 60 | `6af0386442a0937d7371487cea564a7473d7bafcb7bdc11ccb49eb65479ebd23` | none |

The configurations use placeholder hostnames, are not authoritative runtime
identity or bootstrap sources, and are not imported into the twin. Absence of a
recognized pattern does not prove arbitrary configuration is non-sensitive.

## Accepted architecture outcome

- Terraform CLI: exactly `1.15.8`, installation deferred to 8B.
- Provider: exactly `CiscoDevNet/cml2` `0.9.3-beta1`.
- Adoption: separate Terraform-owned twin; no import of the accepted lab.
- State: sensitive, ignored and kept outside the repository.
- Authentication: ephemeral provider-native environment inputs.
- TLS: verified with an operator-controlled controller PEM; no skip-verify.
- Bootstrap: credential-bearing payloads excluded from Terraform state;
  state-free bootstrap deferred to 8D.
- Cutover: deferred; stable management endpoints cannot coexist on both running
  labs.

## Safety result

- Repository changed during discovery: **NO**.
- Terraform installed or invoked: **NO**.
- Terraform apply/import/destroy: **NO**.
- CML changed or lifecycle changed: **NO**.
- NetBox accessed: **NO**.
- OpenBao accessed: **NO**.
- Buildkite runtime accessed: **NO**.
- Device authenticated or commanded: **NO**.
- Device write: **NO**.
- JWT printed or persisted: **NO**.
