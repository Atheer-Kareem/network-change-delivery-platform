# Declared population and exact consumer scopes

CAP-POPULATION-SCOPES implements the following current contract. User acceptance
remains pending in the [authoritative ledger](../roadmap.md).

```text
Git-declared managed population
→ exact typed consumer scope
→ profile/capability projection
→ applicable assurance
→ operation-specific write authority
```

Exact membership does not mean fixed population size. Managed membership alone
never grants write authority. The [current proof population](profile-aware-population-and-realization.md#exact-git-owned-population)
retains devices 1/core-02, 2/edge-junos-01, 8/transit-ios-01 and 9/access-sw-01,
in that canonical order, with unchanged factual/profile/endpoint authority.
This change onboards no real member and migrates no installed service.

## Declaration, resolution and projection

`ProfiledLogicalName` replaces the per-instance enum with a bounded validated
logical-name string. `ProfiledPopulationMember` binds stable NetBox identity,
name, expected role, platform/device type, NOS, automation profile and CML
profile. `ProfiledPopulationDeclaration` requires nonempty ordered membership,
unique IDs/names and exact existing profile admission. Multiple members can
reuse a profile; the automation and CML profile vocabularies remain closed.

`ProfiledPopulationScope` binds only a stable scope identity and exact ordered
selected member facts. Its canonical serialization and SHA-256 identity exclude
unselected managed members. Adding an unrelated member to the full declaration
therefore leaves an unchanged service scope byte-for-byte identical. The
`population_scope(..., declaration=...)` factory validates selection against the
Git declaration; the declaration is admission context, not intrinsic scope content.
Runtime callers still supply their reviewed expected scope. A structurally valid
serialized scope cannot authorize itself or replace that expected scope.

The GET-only NetBox resolver checks the complete tagged population against Git,
including inactive tagged records so they cannot disappear behind an active-only
query. Missing, unexpected, duplicated or mismatched members fail. Only after
full resolution does `ProfiledInventoryPopulation.project()` select a consumer
scope, verifying exact selected facts and canonical order against the resolved
declaration. Unknown, duplicate, reordered or mismatched members fail. NetBox
discovery alone cannot authorize a new member.

| Consumer | Current reviewed scope/projection |
|---|---|
| Persistent LIVE realization | `LIVE_REALIZATION_SCOPE` |
| Disposable STAGING | `STAGING_REALIZATION_SCOPE` plus exact typed topology |
| Profiled host trust | Exact expected realization scope and reviewed CML anchors |
| Oxidized | `OXIDIZED_COLLECTION_SCOPE`; canonical `netbox-device-N` nodes |
| Management-service observability | `OBSERVABILITY_SCOPE`; service from profile |
| SNMP | Selected scope intersected with SHA256/AES128 profile capability |
| Routed underlay / OSPF | Explicit service subjects 1, 2, 8 |
| VLAN | Explicit service subjects 1, 9 |
| ACL | Explicit service subject 1 |
| Batfish reference assurance | Explicit modeled service topology, unchanged |

The current LIVE/STAGING/Oxidized/observability scopes select the proof
population. They reuse reviewed membership data but remain independently named
consumer contracts. Adding an unrelated managed member does not add it to a
service scope. B5 ownership and historical D0 evidence are unchanged.

## Realization and passive runtime

Realization, trust and staging context models require exact scoped membership,
unique stable/name/CML identities, profile pairing and purpose-specific
management bindings. The coordinator checks the expected staging scope before
read-only validation. Leaf realized-device, trust, staging-device and observability
target records retain structural/profile/NOS/service validation without embedding
the full declaration. Their aggregates enforce exact expected scope membership.
READY/freshness and no-LIVE-fallback rules remain.

`CURRENT_LIVE_REALIZATION` separates reviewed CML node identities, labels,
management endpoints and topology data from admission algorithms. LIVE trust
and observability compare against an expected catalog, rather than allowing an
observed key or CML node to authorize itself. The LIVE verifier resolves the
managed population then projects the expected realization scope.

Current LIVE verification and trust-enrollment commands use these reviewed
anchors directly, without per-instance node-ID arguments. Oxidized enrollment
and observability admission retain their explicit lab-ID argument. Changing an
anchor requires a reviewed catalog change, not a command-line identity override.

Oxidized materialization resolves all authority before private publication.
Controller `/nodes.json` and readiness must match the caller's expected scope
exactly, with the managed group, current container, trust digest and freshness.
Collection outside that scope fails. The existing immutable-wheel updater and
machine-identity/ephemeral-source-SecretID architecture are unchanged. Installed
services are not updated by implementation tests.

Observability generation and readiness bind their exact scope and reject extra,
missing or duplicate targets. Multiple instances of one profile produce distinct
stable targets. Current real outputs retain their existing order and services.
SNMP remains capability-derived; IOSv and IOSvL2 remain ineligible. Existing
credential permission and role/policy configuration are unchanged.

The scoped private runtime contracts are `TargetGeneration` v3,
`RealizationAdmission` v4 and `ObservabilityReady` v3. Their former v2/v3/v2
forms lacked the current scope/catalog content and are explicitly rejected as
stale, rather than reinterpreted under their old version labels. The normal
reconciler must republish current evidence; this implementation performs no
runtime migration. Synthetic old canonical fixtures preserve the original
self-digest semantics for regression checks.

## Disposable graph and evidence

Python admits an exact device map and `ProfiledStagingTopology` before Terraform.
Each data link binds endpoint logical names and exact interface names; NetBox
resolves stable interface/cable identities and the profile resolves CML slots.
Unknown endpoints, duplicate link identities/endpoints and wrong physical slots
fail. Management slots come from each resolved NetBox STAGING physical attachment
through its realization profile interface-to-slot map, never the first profile
slot. The same derivation feeds Terraform, management links and data-link
collision admission. The static topology model validates profile interfaces;
collision checks occur where resolved management bindings are available.
Terraform does not discover or select membership.

Delete-only recovery uses retained private inputs without fresh authority reads.
It requires a valid reviewed profile management slot, canonical unique switch
slots, the exact run/device/topology/profile/bootstrap bindings and no retained
data-link collision with management. A valid non-first management slot survives
recovery unchanged; create-only owner-private file protections remain.

For N devices and L data links, expected ownership is N+2 nodes, N+L+1 links,
and 2N+L+5 resources including lab and lifecycle. Every owned resource must be
absent before retirement. Partial ownership admits only the exact known subset
and matching delete-only plan. Current N=4/L=4 remains 6/9/17. The current
core–edge, core–transit, edge–transit and core–access graph and topology digest
remain unchanged; Terraform addresses now use deterministic `for_each` keys.

IOSv's typed boot policy retains first BOOTED → 60-second persistence hold →
STOP → START → second BOOTED, independently for each admitted IOSv subject.
No other profile receives the workaround. No mutation retry was added.
Schema-v3 staging evidence records each selected subject and bounded recycle
attempt/reference. Historical schema v2 retains its transit-specific contract
and reader. New evidence and summaries report actual scoped counts, not `/4`
as architecture. See [staging operations](profiled-disposable-cml-staging.md).

## Classified instance audit

Active source, scripts and staging Terraform were searched for fixed lengths,
four-position tuples, instance names/keys, literal ID sets, expected-node globals,
the removed name enum, `/4` summaries and fixed resource counts. The following
classifies the remaining occurrences by their authority, rather than replacing
historical or service facts mechanically.

| Occurrences / source family | Classification and treatment |
|---|---|
| `profile_inventory.py` current member entries and derived compatibility exports | Current lab/catalog data. Names/IDs remain explicit; declaration/scope algorithms have no fixed count. |
| `profiled_live_cml.py` `CURRENT_LIVE_REALIZATION` | Current lab realization data. Algorithms consume typed catalog/scope; repeated-profile instances need no branch. |
| `architecture_contracts.py` reference examples and closed profile catalog | Catalog/reference data; no per-instance logical-name enum. Profile vocabulary remains closed. |
| `profiled_staging.py` current topology entries | Explicit reviewed topology intent. Digest retained. Resource/address sets derive from scope and links. |
| `ProfiledStagingEvidenceV2`, retained LIVE reconciliation specs/results, NetBox B3/B4 migration scripts | Historical milestone/evidence or bounded migration tooling. Historical identities, counts and accepted bytes stay intact. These helpers do not define current generic admission. |
| `reference_*`, routed underlay, OSPF, VLAN, ACL and `profiled_pr_assurance.py` | Current service/topology intent and serialized assurance identities. Exact modeled membership and invariants remain; service projections isolate unrelated managed members. |
| `profiled_promotion.py` and Buildkite delivery target literal | Explicit current operation/delivery authority, intentionally unchanged. CAP-INTENT-DELIVERY owns broader target selection. |
| `openbao_profiled_config.py` device IDs | Current operator credential configuration data; permission changes are excluded. |
| `observability_realization.EXPECTED_NODES`, staging credential IDs, SNMP eligible IDs | Derived compatibility projections of reviewed scope/catalog/capabilities, not independent membership tables. |
| `scripts/observability/verify_runtime.sh` named endpoints and count assertions | Isolated current-proof-population Docker fixture, not service admission logic. It now resolves a real typed fixture population; synthetic consumer tests separately cover other scope sizes. |
| Parser lengths, UUID/hash lengths, four B5 verticals, four profile interface slots | Protocol/format/profile or service contracts, not managed-population cardinality. |

Generic fixed-population checks were replaced in inventory, realization/trust,
Oxidized source/controller/readiness/reconciler, observability, staging Terraform,
ownership verification, layout/recycle selection and LIVE verification.
Historical ADRs and acceptance records were not rewritten.

## Validation boundary

Synthetic tests exercise 1/2/4/5 members, repeated IOSv and SNMP-capable profiles,
canonical NetBox resolution, exact consumer rejection, isolated service scopes,
scoped readiness/publication, and two independently recycled IOSv instances.
They use temporary/private test roots and simulated providers. Operation admission
and current core-02 promotion regressions remain fail closed. No new OpenBao
deployment credential path or real infrastructure change is part of this proof.
