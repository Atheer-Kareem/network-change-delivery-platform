# Increment 5C fleet rollout acceptance

## Status

Increment 5C live acceptance succeeded on 2026-08-22 at repository HEAD
`b1ae61af5b7f85709d0b48c31cb622c9e1bd37a7` after two explicitly authorized
fleet-deploy attempts. The first attempt was blocked during complete preflight
by the repaired NetBox runtime-token authentication defect; it attempted zero
children and performed zero device writes. Attempt 2 completed the exact
approved canary/wave rollout and final validation successfully.

## Scope

Increment 5C completes process-local stable-device overlap admission and will
exercise the reviewed sequential fleet state machine against a synthetic
personal CML fleet containing at least three deployable devices across Cisco IOS
XE and Junos, including a real persisted wave.

Process-local admission reserves every frozen `inventory_object_id`, including
compliant members, atomically before complete preflight. It is not cross-process
or distributed coordination. No filesystem lock is used or claimed.

## Required acceptance flow

1. Inspect CML capacity and bootstrap any third synthetic device outside NCDP.
2. Discover safe unused physical interfaces read-only.
3. Establish exact synthetic NetBox tags, identities, and narrow OpenBao access.
4. Generate one immutable fleet plan through `fleet-plan`.
5. Independently verify its canonical SHA-256 digest.
6. Run complete read-only fleet preflight.
7. Stop for explicit approval of that exact digest.
8. Only a later separately authorized action may run `fleet-deploy` once.

Attempt 1 was recorded in `.local/fleet-change-live-001.json` and remains
immutable. Attempt 2 was recorded in `.local/fleet-change-live-002.json`.

## Frozen live fleet handoff

The operator credential was first used only through `EnvironmentSecretProvider`
for the mandated bootstrap discovery of synthetic `core-03` at
`192.168.4.15:22`. `AnsibleRunnerCiscoAdapter.discover()` observed hostname
`core-03`, IOS XE `17.18.02`, and disabled, unaddressed, undescribed
`GigabitEthernet2` through `GigabitEthernet4`. Existing SSH host trust was used;
SSH, AAA, and host keys were not changed.

Fresh discovery selected one unused, unprotected physical interface per device:

| Device | Stable device identity | Platform | Selected interface | Stable interface identity | Fresh state |
| --- | --- | --- | --- | --- | --- |
| `core-02` | `netbox:dcim.device:1` | `cisco_iosxe` | `GigabitEthernet3` | `netbox:dcim.interface:7` | disabled, no IPv4 address, no description |
| `edge-junos-01` | `netbox:dcim.device:2` | `junos` | `ge-0/0/2` | `netbox:dcim.interface:8` | operationally down, no IPv4 address, no description |
| `core-03` | `netbox:dcim.device:3` | `cisco_iosxe` | `GigabitEthernet2` | `netbox:dcim.interface:6` | disabled, no IPv4 address, no description |

Synthetic NetBox tags `ncdp-fleet-live-001` and
`ncdp-fleet-interface-live-001` select exactly this population. The stable
`core-03` identity derives the exact OpenBao logical path
`ncdp/devices/3/ssh`, API policy path `ncdp/data/devices/3/ssh`, and non-secret
reference `openbao:kv-v2:ncdp/devices/3/ssh`. The existing personal-lab AppRole
policy permits only exact reads of device paths 1, 2, and 3. The core-03 KV-v2
metadata reported current version 1. Credential values were not printed or
retained in the plan or evidence.

After bootstrap, direct device credential variables were removed from each NCDP
planning and preflight child process. Fresh collection used the normal
read-only NetBox to short-lived AppRole to exact-path OpenBao to vendor-adapter
chain for all three devices. The first preflight used a fresh read-only
SecretID; Attempt 2 used one fresh deployment SecretID and no retry.

`CHG-FLEET-LIVE-001` uses desired description
`managed-by-network-change-delivery-platform-fleet-live-001` and `wave_size: 1`.
The mode-0600 ignored plan contains exactly three `DEPLOYABLE` members and zero
`COMPLIANT` members. Persisted cohorts are:

- Cisco canary: `netbox:dcim.device:1` (`core-02`);
- Junos canary: `netbox:dcim.device:2` (`edge-junos-01`);
- wave 1 Cisco member: `netbox:dcim.device:3` (`core-03`).

The frozen fleet digest is
`sha256:f8bab943b0ab2128072b9560b2ee853363e64325d7a7446d11e4a831f9497ef5`.
The typed model calculation, independent standard-library canonical JSON
calculation, and independent `jq -cS` plus system SHA-256 calculation all
matched the stored digest. All three embedded child-plan digests also verified.

`preflight_fleet` then re-resolved the complete selector and freshly verified
inventory endpoint/platform bindings, stable device and interface identities,
OpenBao provenance, credentials, live hostname, physical-interface existence,
protection state, and exact child preconditions for every member. It returned
`complete fleet read-only preflight succeeded`; all three members succeeded with
absent observed descriptions.

## Attempt results

Attempt 1 (`.local/fleet-change-live-001.json`) remains byte-for-byte unchanged
with SHA-256
`4e0c1f570fe168e3c0805dbdaa57d7d783cbd20af6f7646e8ef13f29c7523830`:
`BLOCKED` during complete fleet preflight because NetBox authentication was
rejected, with zero child attempts, zero writes, and zero retries.

Attempt 2 used the exact approved digest
`sha256:f8bab943b0ab2128072b9560b2ee853363e64325d7a7446d11e4a831f9497ef5`.
Complete preflight succeeded, followed by the exact order `core-02` canary,
`edge-junos-01` canary, and `core-03` wave 1. Each child finished `SUCCEEDED`;
Junos candidate preparation, candidate diff capture, commit-confirmed commit,
independent post-write validation, and confirmation all succeeded. Final
whole-fleet validation succeeded and freshly observed the approved description
on all three interfaces. No retries occurred.

The success-only read-only idempotency check selected three members, found zero
`DEPLOYABLE` and three `COMPLIANT`, and produced no plan artifact.

Fleet rollout makes no fleet-atomicity claim. Admission remains process-local;
there is no cross-process or distributed lock, and distributed locking remains
Increment 7. Successful earlier members are not automatically reverted if a
later member fails.

Increment 5C acceptance is complete.

## Post-acceptance credential closeout

The diagnostic exposure affected only the synthetic Junos device 2 credential.
An intentionally simple synthetic personal-lab Junos credential appeared in
diagnostic output. The operator accepted this lab-only risk. No production,
company, or reused credential was involved. OpenBao and the device were
re-synchronized and normal hardened read-only authentication was verified.

The first automated rotation changed the device but failed to update OpenBao.
The operator then reset the Junos password at the console to the original
disposable lab credential. OpenBao device 2 was synchronized with a CAS-guarded
write from KV version 2 to version 3. Fresh OpenBao-backed Junos discovery
succeeded; hostname, Junos version, interface existence/protection, and the
approved `ge-0/0/2` description remained correct. The temporary recovery
plaintext file was removed after synchronization and verification, and direct
password environment material was unset in the verification process. This
security remediation was independent of the fleet transaction; no fleet
selected interface was written and the fleet-deploy invocation count remained
exactly two.

## Exit-code evidence limitation

A post-success process/command observation returned exit status 2 with
FileExistsError referring to the already-created attempt-2 evidence path.
Available execution evidence cannot establish the exact process boundary that
produced this later error. The persisted fleet record is SUCCEEDED, final
whole-fleet validation succeeded, subsequent read-only idempotency succeeded,
and the normal fleet-deploy SUCCEEDED path returns 0 in the implementation and
offline regression suite. No reproducible fleet-deploy defect was established,
so production code was not changed and no live deployment was repeated.
