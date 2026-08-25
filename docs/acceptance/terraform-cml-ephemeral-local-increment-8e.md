# Increment 8E-2 local ephemeral CML lifecycle acceptance

## Boundary and result

Increment 8E-2 started from merged `main`
`b3ccd893fc530888bd41c7aa5e89bce5fef8bec1` and used staging run identity
`8e2-local-acceptance-01`. The accepted run completed the ADR 0014 lifecycle:

```text
ABSENT -> CREATE at DEFINED_ON_CORE -> STARTED -> READ-ONLY VALIDATION
       -> direct DESTROY -> independently proven ABSENT -> state retired
```

No Buildkite staging step or protected deployment behavior changed. No console
was opened, `ncdp deploy` was not invoked, and neither adapter performed a
device write.

## Fresh realization

The safe JSON plan and apply each reported `13 add / 0 change / 0 destroy`.
Both credential-bearing CML Day-0 values were non-empty and exactly equal to
their fresh local renders without displaying their content.

- lab: `67f71ecc-516c-4cd6-9b20-1d9401e44d04`
- system bridge: `abf2dea8-4c5b-4dab-a1bb-1b2f962ad98f`
- management switch: `50e34633-2afa-40d6-b00a-561526da1f31`
- core-02: `61323833-899a-46be-b11f-967e833ea8c2`
- edge-junos-01: `2562339a-f75b-48d3-862e-cf7c556f3578`
- core-03: `d7eb8510-2c31-44ac-bd80-aea2aa575a37`
- system bridge to management: `ea1862f5-f43b-40ee-8480-0519cd9e4e34`
- management to core-02: `f35b2a49-de01-42f2-b824-3800025357aa`
- management to edge-junos-01: `b75c236f-364a-484d-b370-a4188032426e`
- management to core-03: `d122fe11-020b-42e8-ae6f-18aae95f9397`
- core-02 to edge-junos-01: `c0e8a8cc-22cf-4d9c-88d4-309bc8910fd2`
- edge-junos-01 to core-03: `def51db6-bd59-41d2-b24f-f93ec5b328e5`

The STARTED plan reported only `module.twin.cml2_lifecycle.twin` as an update.
One lab metadata refresh-drift event was reported separately and did not become
a planned lab mutation.

## First-boot readiness and NCDP validation

After Terraform completed the staged STARTED transition, core-02 satisfied the
bounded ARP, ICMP, TCP/22, and TCP/830 boundary after 12.1 seconds. Edge Junos
had booted concurrently and satisfied the same boundary on its first poll. The
Mac neighbor cache independently contained resolved entries for both fixed
management addresses after validation.

Fresh NetBox resolution bound core-02 to `netbox:dcim.device:1`,
`192.168.4.14`, platform `cisco_iosxe`, and unprotected `GigabitEthernet2`. It
bound edge-junos-01 to `netbox:dcim.device:2`, `192.168.4.20`, platform `junos`,
and unprotected `ge-0/0/2`. Credential provenance was respectively
`openbao:kv-v2:ncdp/devices/1/ssh` and
`openbao:kv-v2:ncdp/devices/2/ssh`.

The real `NetBoxInventoryProvider`, `OpenBaoSecretProvider`,
`AnsibleRunnerCiscoAdapter`, `JunosPyEZAdapter`, and shared planning policy
completed identity resolution, strict-host-trust authentication, live state
collection, safe target validation, and plan construction for both devices.
Credentials were retrieved once per device and reused in process memory. The
run exposed a Paramiko 5 incompatibility with the lab's `ssh-rsa` host key; the
project now constrains Paramiko to compatible 4.x and the successful clean run
used 4.0.0. No deployable artifact was executed.

## Cleanup and failure semantics

The successful run intentionally destroyed directly from STARTED. Its safe
destroy plan and apply each contained exactly `0 add / 0 change / 13 destroy`.
CML inspection then proved the lab title, lab UUID, all five node UUIDs, and all
six link UUIDs absent. `terraform state list` was empty before retirement. The
run-scoped local backend state, backup history, and run-specific `TF_DATA_DIR`
were removed together; shared caches were not removed.

During development, one post-create Day-0 readback-shape failure and one
post-readiness client-compatibility failure also triggered exact 13-resource
destruction, independent absence proof, and state retirement. Unit tests cover
create-before-resource failure, validation-triggered cleanup, destroy and
absence failure retention, preservation of primary failure, successful
retirement, and duplicate-state admission rejection. No live destructive
failure was injected.

Final accounting: CML staging resources are absent; the legacy lab remained
stopped; the historical scratch lab was absent; console operations were zero;
device, NetBox, and OpenBao KV/policy writes were zero. Four bounded AppRole
SecretIDs were issued during diagnostic and accepted runs; this was auth-backend
material only and did not alter device credentials. Buildkite staging external
actions were zero.
