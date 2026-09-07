# Profiled main delivery acceptance

## Scope and evidence boundary

This is the canonical current schema-v2 delivery-tail milestone for the personal
MacBook lab. The user supplied and accepted the negative and positive runtime
results below. They were not reconstructed from Buildkite APIs, logs, checks or
live infrastructure during this documentation reconciliation. The artifact bytes
are not reproduced here; their identifiers and reported contents are supplied
evidence, not a new independent digest verification.

Build number, job IDs, exact source/merge SHA for the run, unblocker identity and
runtime timestamps are **not recorded in this acceptance source**. No value is
inferred from an artifact filename or nearby Git history.

## Negative path — scheduling continuation without authority

An earlier current-tail attempt failed live planning/prerequisites. Downstream
steps continued and the human block could still appear, but promotion could not
establish valid authority. Deployment independently returned **NO WRITE**. The
final evidence step did not fabricate a typed execution record.

This demonstrates `scheduling continuation ≠ deployment authorization` and
`human authorization cannot override failed prerequisites`. It does not imply
that every missing artifact in a different run proves no write occurred.

## Positive path — authorized change with independent validation

A later fresh current-main run completed schema-v2 live planning, immutable
promotion, human authorization, an admitted real virtual-device write,
independent post-validation and a typed `ProfiledChangeRecord`.

| Field | Supplied result |
|---|---|
| Device | `core-02 / netbox:dcim.device:1` |
| Interface | `GigabitEthernet2 / netbox:dcim.interface:2` |
| Change | `CHG-PROFILED-LAB-DEMO` |
| Before description | `ncdp-pr132-live-core-14b725b` |
| Desired description | `managed-by-ncdp-profiled-demo` |
| Independently observed final description | `managed-by-ncdp-profiled-demo` |
| Schema / record type | `2 / profiled_change_record` |
| Outcome | `SUCCEEDED` |
| Write attempted | `True` |
| Recovery attempted | `False` |
| Artifact | `profiled-01a07b9e-6eed-4ef9-ba22-9ed5af1e2112-record.json` |

Exact supplied digests:

- Plan: `sha256:993da66158218887b0e45f89eed3685dca4181b3026a1f814f598352414256c0`
- Promotion: `sha256:be250015952bb40aeeaa23d8ef6e7ae47ad415fe6e7e581cc18c2c7378150448`
- Evidence: `sha256:53e88d3ce458dd05d9b591c139b919d9942ce83a253841af40e4fb936b6b9121`

The supplied record reports fresh preflight success, execution success and
post-validation observing desired state. **`execution.changed == false` is also
present**, despite before/post observations proving a description transition.
The current adapter derives that flag from provider result metadata, defaulting
missing metadata to false. It is not a reliable observed-transition predicate.
This record is not silently corrected; semantics and consistency improvements
belong to [CAP-OUTCOME-TRUTH](../roadmap.md#cap-outcome-truth--truthful-profiled-delivery-outcomes).

## Source-confirmed controls and limits

The [workflow](../architecture/buildkite-workflow.md), `profiled_promotion.py`,
`scripts/buildkite/profiled_delivery.py` and their static/unit tests confirm
same-build engineering receipts, Batfish and CML success digests, exact plan
bytes/digest, promotion identity and fieldless human authorization are required
and independently revalidated before CLI deployment. Soft failure affects
scheduling only; mutation retries remain disabled.

The user-reported successful main chain establishes the current delivery
milestone, including its required assurance prerequisites. This source does not
supply separate raw staging/Batfish receipts. Batfish models routed underlay,
OSPF, VLAN and selected ACL/service behavior; it is not derived from this
interface-description plan. Disposable CML proves realization, readiness,
trust, bounded read-only validation and cleanup/absence, not candidate-write
rehearsal or deployment authority.

Current main delivery selects the fixed core-02 demo intent; the schema-v2 CLI
also admits vJunos interface-description operations. This milestone is not a
main-pipeline Junos write acceptance. Earlier independently authorized Cisco
and Junos CLI acceptance remains in the
[profiled deployment record](profiled-deploy-live-acceptance-pr132.md).
IOSv/IOSvL2 write admission, fleet rollout, recovery writes, service writes and
production deployment suitability are not established here.

Plans, promotions and execution records are typed artifacts retained through
the current private delivery state/artifact path. They do **not yet enter the
historical durable AuditStore, PRE/write/POST correlation or viewer chain**.
That restoration belongs to CAP-DURABLE-EVIDENCE and CAP-CONFIG-CHRONOLOGY;
independent Oxidized history remains supporting observation, not proof of cause.

Already-compliant planning produces no deployable plan and cannot establish
promotion authority. The current downstream Buildkite presentation does not yet
provide the refined typed no-change outcome proposed in CAP-OUTCOME-TRUTH.
Never reset a device merely to manufacture a change for demonstration.

This acceptance does not authorize a new live attempt. The local Cisco runtime
prerequisite was subsequently merged in [#140](https://github.com/Atheer-Kareem/network-change-delivery-platform/pull/140)
and explicitly user-accepted through offline CLI-boundary tests; see the
[capability ledger](../roadmap.md). PR/development CML staging remains temporarily
skipped under its ACTIVE exception; main still requires real staging evidence.
