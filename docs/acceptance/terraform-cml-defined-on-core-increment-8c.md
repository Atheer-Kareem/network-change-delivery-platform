# Terraform/CML `DEFINED_ON_CORE` acceptance — Increment 8C

## Accepted scope

Increment 8C-3 created the separate Terraform-owned personal-CML twin from
protected `main` commit `362cf2d76b25db5efdee32595129ca57444d2cc8` and accepted
its initial `DEFINED_ON_CORE` state. No node was started or booted. The first
`STARTED` transition, operational bootstrap, reset/recreate, and cutover remain
outside this acceptance.

The run used Terraform `1.15.8` and exactly `CiscoDevNet/cml2`
`0.9.3-beta1`. Terraform state remained in approved encrypted operator storage
outside the repository with restrictive file permissions. No user-specific
state path is recorded here.

## Pre-apply evidence

The exact controller reported ready and valid health, a compliant CML Personal
license with 20-node capacity, and compute admission `READY`. Immediately before
creation it contained 5 licensed nodes, all 5 running in the accepted legacy
lab. Free resources were 16,232,001,536 bytes RAM and 911,335,964,672 bytes
disk. This snapshot admitted the five planned definitions only; it is
observational evidence and does not accept simultaneous heavy runtime.

The accepted legacy lab `09605569-0468-4fc4-8684-beb5a1342b9c`, titled
`Lab at Wed 21:44 PM`, was present. Its current nodes were `ext-conn-0`,
`unmanaged-switch-0`, `cat8000v-0`, `vjunos-router-0`, and `cat8000v-1`, all
`BOOTED`. The exact title `NCDP Terraform Twin` had zero matches before apply.

Both the final unsaved speculative plan and Terraform's independently generated
interactive apply-time plan showed exactly 13 creates, 0 changes, and 0
destroys:

- 1 `cml2_lab`
- 5 `cml2_node`
- 6 `cml2_link`
- 1 `cml2_lifecycle`

The desired lifecycle was exactly `DEFINED_ON_CORE`. Router configuration was
explicitly empty, no stable management address or credential-bearing payload
was present, and the accepted connector and image matches were each unique.
The apply used Terraform's interactive confirmation prompt; it did not use
`-auto-approve` or a saved plan.

## Created realization

The apply completed with 13 added, 0 changed, and 0 destroyed. Terraform state
contains exactly those 13 managed resources. Safe realization identifiers are:

| Resource | CML UUID |
| --- | --- |
| Twin lab | `1a00ab4d-e44f-4a80-a8da-c73a329d6878` |
| `system-bridge` | `278c9af6-2294-477d-b796-fca120ccbce7` |
| `management-switch` | `7ce47ca9-b79c-42ad-b7fa-2d18f69e7450` |
| `core-02` | `44c3b115-68fb-474b-b30c-d291ad0af55c` |
| `edge-junos-01` | `077e8ab9-d78d-43b8-9ec1-30e9c3d9de03` |
| `core-03` | `cb5770bd-e59d-44a6-9927-d1accd6b627b` |
| Lifecycle | `846dc9f8-7b7a-41b9-8bc5-aac287911096` |

The six link UUIDs are
`6f9b7af6-d76f-42ac-94db-82469787f1bf`,
`85c83a4f-22bf-41f7-ba81-4a8486b478a5`,
`e7ad1346-6f0d-4e25-88c3-e9cf4d4f965d`,
`d973222d-f4a1-472b-8670-f5dc91bcc2ff`,
`305f4cfa-3592-4bb6-9bab-961e93270517`, and
`995ed154-c778-4f0c-b444-ab90ef9f281e`.

Direct CML verification found exactly one `NCDP Terraform Twin` in
`DEFINED_ON_CORE`, with 5 nodes and 6 links. Every node remained
`DEFINED_ON_CORE`; no node was `STARTED` or `BOOTED`. Realizations were:

- `system-bridge`: `external_connector`, dynamically resolved `System Bridge`
- `management-switch`: `unmanaged_switch`, with no Terraform-supplied
  functional configuration
- `core-02`: `cat8000v` / `cat8000v-17-18-02`
- `edge-junos-01`: `vjunos-router` / `vjunos-router-23-2r1-15`
- `core-03`: `cat8000v` / `cat8000v-17-18-02`

The exact accepted links were:

```text
system-bridge slot 0 -- management-switch slot 0
management-switch slot 1 -- core-02 slot 0 / GigabitEthernet1
management-switch slot 2 -- edge-junos-01 slot 0 / fxp0
management-switch slot 3 -- core-03 slot 0 / GigabitEthernet1
core-02 slot 3 / GigabitEthernet4 -- edge-junos-01 slot 1 / ge-0/0/0
edge-junos-01 slot 2 / ge-0/0/1 -- core-03 slot 2 / GigabitEthernet3
```

`core-02` `GigabitEthernet2` and `GigabitEthernet3`, `edge-junos-01`
`ge-0/0/2`, and `core-03` `GigabitEthernet2` remained unlinked.

## State and configuration secrecy

Actual Terraform state inspection found each router's `configuration` exactly
empty and no non-empty `configurations` content. Direct CML API inspection found
one named stored-configuration object per router, each with zero-length content:

| Router | Stored configuration | Content |
| --- | --- | --- |
| `core-02` | `iosxe_config.txt` | zero length |
| `edge-junos-01` | `config/juniper.conf` | zero length |
| `core-03` | `iosxe_config.txt` | zero length |

No router was authenticated to and no device command, write, bootstrap, or
configuration-generation action occurred. A bounded exact-byte scan of the
external Terraform state, Terraform working metadata, and repository working
tree found no persisted CML token and no unexpectedly persisted CML CA PEM.

The required post-apply refresh plan reported 0 add, 0 change, and 0 destroy.
State inspection after that refresh again found the three router configuration
fields empty and no non-empty `configurations` content.

## Legacy invariant and remaining work

After apply, the accepted legacy lab retained its UUID, title, `STARTED`
lifecycle, five node UUIDs and labels, and their `BOOTED` states. Terraform
operations were confined to the new twin. This does not claim byte-for-byte
device-state equivalence because device authentication was prohibited.

The first `STARTED` transition remains pending a separate fresh capacity
admission. `STOPPED` lifecycle acceptance also remains pending. Increment 8D
will address state-free bootstrap and authorized reset/recreate behavior.
