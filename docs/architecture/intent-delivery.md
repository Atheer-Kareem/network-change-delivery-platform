# Committed intent-selected delivery

CAP-INTENT-DELIVERY implements this boundary; user acceptance remains pending in
the [ledger](../roadmap.md#cap-intent-delivery--intent-selected-generic-delivery).

```text
reviewed committed InterfaceDescriptionIntent
→ exact Git/NetBox managed target resolution
→ profile/operation admission
→ immutable plan or typed compliance
→ intent-bound promotion when a plan exists
→ fieldless human authorization
→ independently revalidated deployment
```

Intent selects a target; target selection grants no authority. Managed membership
is not write eligibility, and human unblock is not a selector.

## One fixed source, one operation

`load_committed_intent(checkout)` reads only
[`deployments/live/profiled-demo.yaml`](../../deployments/live/profiled-demo.yaml).
It uses directory-relative file descriptors with no-follow checks for the root,
parent directories and final file. The file must be regular, nonempty and at
most 16 KiB. Safe YAML parsing admits exactly one document with unique mapping
keys; the existing frozen, extra-forbid `InterfaceDescriptionIntent` validates
all fields. The logical target must be Git-declared. No environment override,
metadata selector, arbitrary path, discovery, fallback or default target exists.
The existing trusted hook/driver owns clean checkout and exact commit admission.

The file still selects `CHG-PROFILED-LAB-DEMO`, core-02, GigabitEthernet2 and
`managed-by-ncdp-profiled-demo`. These are reviewed data, not control-plane
constants. No active production intent changed to manufacture a network write.

The only supported kind is `interface_description`. The planner resolves logical
name to the exact population member and stable device/interface before operation
admission. CAT8000V and vJunos remain eligible; IOSv and IOSvL2 remain denied.
Existing LIVE trust, protected interfaces, credentials, preflight and vendor
transaction semantics are unchanged. No intent carries an endpoint or host key.

## Independent semantic binding

`admit_intent_result(intent, result)` binds change ID, kind/operation, logical
target, interface name and desired description for both `ProfiledDeploymentPlan`
and `ProfiledComplianceRecord`. The result models and planner continue to own
stable identities, profile/NOS, endpoint, credential reference, operation
admission, observed state and transaction facts; the binder does not rebuild a
write or infer authority from target membership.

Planning loads the committed intent and publishes exactly one result. Planning
annotations derive identities, profile, interface, state and operation from the
validated result. Only a real plan displays a transaction strategy. Promotion,
deployment and final evidence independently reload the committed intent before
validating the downloaded same-build result. A changed intent cannot authorize
an old plan, even if the old artifact and promotion remain internally valid.

`promote(..., intent=...)` requires a validated plan matching that intent plus
all current engineering/Batfish/CML receipts. `authorize(..., intent=...)`
reconstructs the expected promotion and compares the exact plan bytes, canonical
plan digest, build/commit, target/device, receipt digests and promotion metadata.
The unblocker UUID is opaque authorization provenance, never target selection.
The fieldless block, exact DAG, queues, retry zero and protected hook are unchanged.

## Compatible evidence contracts

`ProfiledPromotion` remains schema v2. Its field set, meanings and canonical
serialization are unchanged; bounded change/target/device fields replace demo
Literals. Target/device pairing must exist in the Git population. Those fields
are required and derive from the plan; valid pairing alone cannot mint promotion.
The exact synthetic pre-capability core promotion fixture retains its original
bytes and digest. No intent digest field is needed: the exact commit selects the
fixed YAML, every supported intent field enters the semantic binder/plan, and
promotion already binds the plan digest and exact artifact bytes.

The existing profiled durable envelope remains schema v1 around schema-v2
artifacts. Offline composition now proves a promoted Junos EXECUTION envelope,
exact byte and plan correlation, fieldless authorization provenance, AuditStore
round-trip and a current Junos chronology child. No schema or historical artifact
migration occurs. This is no claim of a new LIVE Junos write.

Both Cisco and Junos compliance paths publish the existing durable COMPLIANCE
family without plan, promotion, execution record or chronology. Continuing the
static block grants zero write authority. Independent chronology maps stable
`netbox:dcim.device:N` to `netbox-device-N`; causality remains NOT_PROVEN.

## Preserved assurance and future boundaries

Batfish remains the existing B4 D1 assurance prerequisite, not validation of the
exact interface-description candidate. CML remains same-build realization and
integration assurance, not a write rehearsal. Main requires real CML success;
the PR/development exception remains ACTIVE. Existing deploy OpenBao permission
remains devices 1/2 with unchanged role, policy, TTL, token uses and persistent
personal-lab SecretID tradeoff. No installation or credential update is required.

One intent selects one explicit device/interface. Profile-reuse write admission,
selectors, lists, fleet/waves and operation-bound assurance are excluded and
retain their separate ledger capabilities.

## Classified target-coupling audit

The audit searched active `src/`, `scripts/` and `deployments/` for
`CHG-PROFILED-LAB-DEMO`, `managed-by-ncdp-profiled-demo`, `core-02`,
`netbox:dcim.device:1`, `netbox:dcim.interface:2`, `GigabitEthernet2`,
`cat8000v_iosxe`, `cisco_targeted_inverse`, `profiled-demo.yaml`,
`admit_demo_plan`, `CHANGE_ID` and `DESCRIPTION`. Prefix matches such as interface
22 are included. The table accounts for every remaining matching file.

| Files / matching-line counts | Classification and retained meaning |
|---|---|
| `deployments/live/profiled-demo.yaml` (4); `profiled_intent.py` (1) | 1 — Current committed intent data and its single fixed source path |
| `architecture_contracts.py` (4) | 2/3 — Closed profile/transaction/interface catalog and historical device vocabulary |
| `profile_inventory.py` (7) | 2 — Git population and reviewed service-scope data |
| `profiled_planning.py` (3); `profiled_execution.py` (1) | 2 — Vendor transaction strategy, not instance selection |
| `profiled_staging.py` (6) | 2/3 — Reviewed topology data and historical v2 evidence reader |
| `profiled_live_cml.py` (6) | 2/3 — Reviewed LIVE links and retained B3 realization operation |
| `routed_underlay.py` (10); `ospf_triangle.py` (15); `vlan_service.py` (24); `security_policy.py` (16) | 2 — Explicit bounded B4 service subjects, topology and invariants; not generic description delivery |
| `reference_data_plane.py` (2); `reference_routing_identity.py` (3); `reference_vlan_service.py` (3); `profiled_pr_assurance.py` (1) | 2 — Reviewed reference/service assurance facts |
| `deployments/live/promotion/policy.yaml` (2); `deployments/live/promotion/baseline/configs/core-02.cfg` (2) | 2 — Existing Batfish assurance input, not the active write intent |
| `scripts/observability/verify_runtime.sh` (2); `verify_snmp_runtime.sh` (4) | 4 — Isolated disposable runtime-test expectations; no protected delivery selection |
| `models.py` (5); `workflow.py` (1); `snmp_provisioning.py` (3) | 2/3 — Vendor strategies in retained historical contracts/workflows |
| `buildkite_configuration_observation.py` (1) | 3 — Historical schema-v1 observation wrapper, not current chronology |
| `scripts/netbox/migrate_b3_inventory.py` (10); `migrate_b3_data_plane.py` (5); `migrate_b4_vlan_gateways.py` (1); `migrate_b4_ospf_router_ids.py` (3) | 3 — Retained migration preconditions/data; not run or modified |
| `profiled_promotion.py`; `scripts/buildkite/profiled_delivery.py` | 5 — Demo constants/tuple and literal target authority removed; no remaining search matches |

Categories 1–4 are retained evidence/data or closed profile/service behavior.
Synthetic test fixtures and historical acceptance documents remain explicit about
the subjects tested. A static regression forbids demo-target dispatch in the
current intent, promotion and delivery modules. B4 service memberships and
historical migration logic were not generalized as part of this capability.
