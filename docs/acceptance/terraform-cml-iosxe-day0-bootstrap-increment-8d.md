# Terraform CML IOS XE Day-0 bootstrap — Increment 8D

## Accepted scope

Increment 8D-2B accepts Terraform/CML Day-0 bootstrap as the zero-console IOS XE
manageability path for the personal digital twin. The implementation began from
protected `main` commit `94575e3bf0c3358a765073885b2f4545d9108205` and used
CML lab `NCDP Terraform Twin` (`1a00ab4d-e44f-4a80-a8da-c73a329d6878`),
CAT8000V image `cat8000v-17-18-02`, and pinned provider
`CiscoDevNet/cml2` `0.9.3-beta1`.

Changing `cml2_node.core_02.configuration` replaced the previously started
`core-02` realization and both links that referenced its UUID. The old node UUID
was `44c3b115-68fb-474b-b30c-d291ad0af55c`; the accepted new UUID is
`6bf4d64d-eabd-41d8-8df5-ec7d665db9c1`. The replacement apply changed only
`cml2_node.core_02`, `cml2_link.management_core_02`,
`cml2_link.core_02_edge_junos_01`, and `cml2_lifecycle.twin`. It used an
interactive unsaved plan and apply; no saved plan was created.

## Authority and secret-state boundary

Fresh NetBox resolution supplied the unchanged stable identity
`netbox:dcim.device:1`, hostname `core-02`, platform `cisco_iosxe`, and primary
IPv4 `192.168.4.14/24`. NetBox still marks `GigabitEthernet1` protected and
identifies unprotected `GigabitEthernet2` as `netbox:dcim.interface:2`. NetBox
was not changed or duplicated.

The existing OpenBao credential remained at
`openbao:kv-v2:ncdp/devices/1/ssh`. The existing `ncdp-personal-lab` AppRole,
policy, 1,800-second/10-use SecretID contract, and 300-second/one-use token
contract remained unchanged. Bounded SecretIDs and tokens were never printed.
No credential was rotated and no KV write occurred.

Under ADR 0013's personal-lab exception, the rendered credential-bearing Day-0
material is deliberately present in both external Terraform state and CML
stored configuration. Direct checks established:

- CML Day-0 stored configuration non-empty: **YES**;
- Terraform `core_02.configuration` non-empty: **YES**;
- credential-bearing material intentionally persisted in both: **YES**;
- actual credential value disclosed in Git, plans, normal output, evidence, or
  PR content: **NO**; and
- external state parent/file permissions: `0700`/`0600`.

The Git template contains placeholders only. No credential tfvars or saved
Terraform plan exists. This accepted tradeoff is limited to the personal lab
and is not a production secret-distribution design.

## Zero-console manageability

The new CAT8000V first boot consumed the CML `iosxe_config.txt` Day-0 payload.
Manual browser-console configuration count was **0**. Without console input,
the router made `192.168.4.14` available on `GigabitEthernet1`, opened TCP/22
and TCP/830, and authenticated with the unchanged OpenBao credential. Strict
read-only collection observed hostname `core-02`, IOS XE `17.18.02`, protected
`GigabitEthernet1` at `192.168.4.14/24`, and present, unprotected
`GigabitEthernet2`. Day-0 included no Gi2 description or other NCDP-managed
intent.

Replacing the VM changed its RSA host key. The prior realization fingerprint
was `SHA256:2ecn6aaFjg730qXmwqczoWUHZ2D4kJWuVoaSLQJsTKc`; the new fingerprint is
`SHA256:aUrJQXSMUXZPBalSGL1t3zbtoC+D0h2s7wII69xK5Ro`. Only the
`192.168.4.14` known-host entry was replaced after the exact new UUID was
BOOTED, its Day-0 hostname/address markers were independently checked, and the
legacy realization was confirmed STOPPED. Global host-key checking remained
enabled.

## Read-only NCDP compatibility

The existing production path—`NetBoxInventoryProvider`,
`OpenBaoSecretProvider`, and `AnsibleRunnerCiscoAdapter`—resolved the stable
device/interface identities and unchanged credential provenance, then completed
fresh strict-host-key SSH collection. `ncdp plan --netbox --openbao` produced an
immutable deployable Gi2 description plan because Day-0 intentionally leaves
Gi2 blank. A separate fresh preflight confirmed the same identity, platform,
credential reference, hostname, version, interface existence, and protection
boundary.

Only safe plan metadata was inspected and the ignored temporary plan was
deleted. NCDP deploy was **not** invoked and NCDP device writes were **0**.

## Recreated-link lifecycle normalization

Replacing the started core-02 also recreated its attached links. The new
`core-02` to `edge-junos-01` link
`602792ef-fb20-403a-87dc-38219520a643` initially appeared
`DEFINED_ON_CORE`. CML refused to start it while its endpoint interfaces were
down. Capacity admission then found 14 free vCPUs and 31,211,692,032 bytes free
RAM for the temporary 5-vCPU/10,240-MiB endpoint footprint.

Exactly new core-02 and Terraform `edge-junos-01` were started. When both
endpoint VMs were running, CML transitioned the exact link to `STARTED`; every
other link and core-03 remained STOPPED. The exact link was then stopped to
`STOPPED`, and edge-junos-01 was stopped. No Junos console was opened, no Junos
configuration was inspected or changed, and no device command was sent. This
was CML operational-state normalization, not an NCDP configuration dependency.

## Restart and final invariant

With the management infrastructure available, the same new core-02 UUID was
stopped and started again. Manual console configuration remained **0**. The
router automatically returned to BOOTED, TCP/22 and TCP/830 became reachable,
and strict OpenBao-backed SSH again observed hostname `core-02`, IOS XE
`17.18.02`, Gi1 `192.168.4.14/24`, and present Gi2.

Final cleanup left all five Terraform twin nodes and all six links STOPPED. All
five accepted legacy-lab nodes remained deliberately STOPPED. A final unsaved
Terraform plan using freshly resolved NetBox/OpenBao runtime values was 0 add,
0 change, and 0 destroy. The external Terraform and CML Day-0 configurations
remain non-empty by design; NetBox, the OpenBao role/policy/KV path/device
credential, and the legacy lab were unchanged.

## Interpretation and remaining work

Success proves controlled IOS XE replacement can automatically materialize the
minimum personal-lab management bootstrap, preserve unchanged stable inventory
and credential authority, pass strict read-only NCDP planning/preflight, and
survive normal restart without console configuration. Terraform still does not
own Gi2 description intent, routing, deployment policy, approval, recovery, or
other NCDP-managed configuration.

Increment 8 remains in progress. Junos Day-0 bootstrap is next and should reuse
this proven pattern. Whole-lab destroy/recreate, reset/wipe reconstruction, full
cutover, NCDP deployment against a recreated twin, and permanent legacy
retirement remain pending.
