# Profile-reuse interface-description admission

CAP-PROFILE-REUSE-WRITE is **IN PROGRESS**. This implementation checkpoint has
only offline/temp evidence; runtime acceptance is pending. The accepted
[intent-delivery](intent-delivery.md) flow and existing active core-02 intent
remain unchanged.

## Two independent gates

```text
managed subject → exact automation profile → explicit operation admission
→ existing profile families → existing planner/executor/writer lifecycle
```

Family compatibility is not operation admission. Operation admission is not
complete deployment authority. Managed membership grants no write authority.

| Reviewed profile | `interface_description` operation | Protected Buildkite credential scope |
|---|---|---|
| `cat8000v_iosxe` | Admitted | Device 1 available |
| `vjunos_router` | Admitted | Device 2 available |
| `iosv_159_3_m12` | Admitted | Device 8 not currently permitted |
| `iosvl2_2020` | Admitted | Device 9 not currently permitted |

`PROFILED_OPERATION_ADMISSIONS` has four explicit reviewed entries. It is not
computed from the automation catalog, Cisco family, population or passive scope.
Future profiles require their own reviewed operation admission. The closed
profile vocabulary and the sole `interface_description` operation are unchanged.
At this capability's acceptance, the dedicated
`ncdp-buildkite-profiled-deploy` policy had `DEVICE_IDS = (1, 2)` and this
implementation made no credential change. CAP-PROFILED-ROLLOUT subsequently
expanded and separately accepted the exact protected set 1/2/8/9; profile reuse
alone still cannot authorize a write. See [rollout
acceptance](../acceptance/profiled-rollout.md).

## Reused Cisco lifecycle

`_operation_admission(profile_id)` derives the reviewed lifecycle from each
unchanged profile. CAT8000V uses IOS-XE; IOSv and IOSvL2 use IOS. Their existing
families are `ansible_network_cli`, `cisco_ios` adapter/renderer,
`cisco_ios_facts` collector, `cisco_targeted_inverse` recovery, SSH/22. There is
no confirmed timeout or confirmation operation.

`ProfiledWriteTarget` remains frozen and binds exact device/interface, logical
name, LIVE endpoint, hostname, protection and profile-local operation admission.
The Cisco writer first revalidates that exact catalog entry, then checks the
Cisco lifecycle families. It contains no device-name or Cisco profile-ID dispatch.
The same `AnsibleRunnerCiscoAdapter`, `apply_interface_description.yml` and
`cisco.ios.ios_config` task consume the existing `CiscoConfigArtifact` parent and
lines. Profile-bound Paramiko trust, no auto-add and exact Ansible runtime pins
(`ansible.netcommon 8.6.0`, `cisco.ios 11.4.2`) remain unchanged.

Approval digest validation precedes runtime verification; runtime verification
precedes credentials and device preflight. Inventory owns interface protection:
the current IOSv/IOSvL2 `GigabitEthernet0/0` is protected. Planning rejects it
before secret reference/load or collection. No first-interface inference exists.
Fresh preflight revalidates identity, profile, endpoint, admission, credential
reference and observed precondition before one forward command maximum.

The forward artifact is `interface <exact-interface>` plus `description NEW`.
The frozen inverse restores the original description or `no description`.
Known failure and uncertain write never retry or invoke speculative recovery.
Independent POST decides success, regardless of provider `changed=True/False/None`.
Only known forward success plus valid, matching-identity POST observing a different
description permits one inverse. Fresh recovery observation must match hostname,
interface and original description to establish RECOVERED. Missing/uncertain
observations and identity mismatch cannot grant inverse eligibility. Evidence
failure after possible execution never replays the device command.

## Offline proof and unchanged evidence

Temporary provider fixtures exercise device 8 (`transit-ios-01`, `192.168.4.16`,
`GigabitEthernet0/1`, stable interface 14) and device 9 (`access-sw-01`,
`192.168.4.17`, `GigabitEthernet0/1`, stable interface 18). Exact credential
provenance is bound to the corresponding device, using test doubles only.
Neither fixture changes switchport, VLAN, routing or management configuration.

The matrix covers all four reviewed planning/compliance profiles and all three
Cisco execution profiles: artifact/inverse equality, protected interfaces,
stale identity/profile/endpoint/reference/state, runtime failure, one-shot success,
known failure, ambiguity, POST safety, verified recovery and recovery uncertainty.
The real Ansible adapter with mocked Runner proves identical playbook, connection,
network OS plugin, trust and artifact parameters for all three Cisco profiles.
An absent catalog entry or tampered lifecycle fails before the provider.

IOSv/IOSvL2 use the unchanged generic intent → plan → promotion → authorization
composition with synthetic authority, followed by simulated typed execution,
temporary AuditStore persist/read/verify, exact artifact-byte correlation,
chronology child/receipt and final evidence. This does not impersonate the real
protected deploy credential role. COMPLIANCE uses one compliance artifact, with
no promotion, authorization, assurance, execution or chronology activity.
Chronology maps device 8/9 to `netbox-device-8`/`netbox-device-9`; causality remains
`NOT_PROVEN`. No real Oxidized history or AuditStore record is created.

No serialized schema changes: operation admission v1; deployment plan,
compliance, promotion and change record v2; durable envelope v1; current chronology
v1. Existing core/Junos evidence and the original promotion-v2 byte/digest
regression remain valid. Historical acceptance documents describe admission at
their own milestones and are not rewritten.

## Preserved boundaries

The active intent, pipeline graph, main-only/non-PR protected tail, retry zero, fieldless
human block, hook and same-build prerequisites are unchanged. Batfish is the
existing B4 D1 prerequisite, not exact description-candidate assurance. CML is
realization/readiness/trust/read-only integration and cleanup assurance, not a
candidate write rehearsal. Runtime-relevant PR/development CML staging is
restored; the protected tail remains main-only. The
IOSv 60-second persistence recycle is realization policy, never configuration
recovery.

SNMP SHA256/AES128 remains device 1/2 only. Routed underlay and OSPF remain 1/2/8,
VLAN 1/9, ACL 1. No unrelated L2, routed, ACL, SNMP, arbitrary IOS or fleet write
is admitted. Rollout remains USER APPROVED and operation-bound assurance DEFERRED.
No real device, NetBox, CML, OpenBao, installed service or AuditStore access is
needed for this implementation.

## Classified coupling audit

The source/docs audit searched `IOSV_159_3_M12`, `IOSVL2_2020`,
`CAT8000V_IOSXE`, `VJUNOS_ROUTER`, `PROFILED_OPERATION_ADMISSIONS`,
`does not admit`, `operation denied`, `write admission`, `exact two-profile`,
`two-profile write surface`, `NetworkOS.IOSXE` and `_validate_cisco_target`.

| Classification | Disposition |
|---|---|
| Current operation authority | `profiled_planning.py`: add explicit IOSv/IOSvL2 entries; `profiled_write_adapter.py`: replace CAT8000V-only check with admitted lifecycle validation. No other authority change. |
| Current documentation | README, change lifecycle, Cisco vertical, population/realization, overview, intent delivery and Buildkite workflow/operations now distinguish operation admission from credential permission. |
| Superseded negative tests | Planning, intent, Buildkite, population and migration-contract tests now test absent explicit admission or protected credential denial. Exact membership and no authority from scopes remain enforced. Execution/runtime/audit matrices extend existing fixtures. |
| Historical acceptance/ADRs | Preserve old denials and original bytes, including population and intent acceptance, migration closure and B3/B4 milestones. |
| Unrelated profile/service facts | Preserve automation/CML catalogs, NOS-specific collectors, vJunos transaction, SNMP capabilities, B4 subjects, Batfish topology, realization/recycle and historical schema readers. Cisco adapter module description now correctly includes IOS. |

Passive-scope projection cannot mutate the operation catalog. Static regression
requires explicit catalog keys and forbids profile-ID selection in the Cisco
family validator; catalog absence is tested independently of compatible families.

Remaining active source matches outside the two admission points are classified
as unchanged profile/service facts: `architecture_contracts.py`,
`profile_inventory.py`, `profile_read_only_adapter.py`, `profiled_execution.py`,
`observability_realization.py`, `oxidized_source.py`, `profiled_live_cml.py`,
`profiled_staging.py`, `profiled_staging_cml.py`, `routed_underlay.py`,
`ospf_triangle.py`, `security_policy.py`, `vlan_service.py`,
`scripts/cml/verify_profiled_live.py` and
`scripts/observability/prepare_snmp_synthetic.py`. In particular, SNMP capability
checks, NOS-specific collection and realization slot/boot policy are not
interface-description admission and remain intact.
