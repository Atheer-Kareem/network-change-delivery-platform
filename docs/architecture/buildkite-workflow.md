# Buildkite personal-lab workflow

This is a continuation-oriented personal-lab demonstration pipeline, not a
merge-blocking CI gate. Every repository command has `soft_fail: true`;
the validation wait has `continue_on_failure: true`. Applications keep their
real nonzero exits and truthful evidence. Soft-failed dependencies permit
downstream scheduling, without `allow_dependency_failure`. Cancellation,
unavailable agents, failed graph upload, and infrastructure loss are not
converted into successful execution.
These are Buildkite's documented [dependency semantics](https://buildkite.com/docs/pipelines/configure/depends-on)
and [wait semantics](https://buildkite.com/docs/pipelines/configure/step-types/wait-step).

All 13 engineering checks remain visible, without path filtering. Automatic
and manual command retries are disabled. A corrected or uncertain attempt
requires a new commit/build and any independently required reconciliation.

```text
Engineering validation → validation-complete → Batfish (PR path ends here temporarily)
                                                main only ↓
                                             disposable CML
                                                       ↓
                             profiled-plan → promotion → HUMAN BLOCK
                                                       ↓
                                  profiled-deploy → deployment evidence
```

Canonical PRs temporarily skip CML and cannot schedule the write tail.
Non-main development builds also skip CML. Canonical non-PR main builds retain
the complete graph and real same-build CML success prerequisite. The approved
[temporary exception and mandatory restoration condition](../roadmap.md#temporary-development-workflow-exceptions)
are tracked in the capability ledger: restore PR staging on user request or
before final integrated roadmap acceptance. No success evidence is synthesized
for skipped staging. Batfish independently rejects arbitrary
repositories/non-PR branches; its historical key remains
`pr-batfish-assurance`, but its visible label is general. The bootstrap simply
uploads the reviewed `.buildkite/pipeline.yml`. There is no separate demo
projection, flag, or renderer.

## Truthful continuation, independent authorization

The existing aggregate GitHub status
`buildkite/network-change-delivery-platform` and external GitHub rulesets are
not changed. **A failed command no longer necessarily blocks merge via that
status.** A green aggregate is not validation, assurance, or delivery acceptance.
The deployment boundary instead requires all engineering success receipts,
both verified assurance success digests, the exact same-build immutable plan
and promotion, and the fieldless human unblock. Human approval cannot override
missing or invalid prerequisites.

Each engineering command runs under strict shell failure handling and publishes
its build/commit/step-bound success receipt only after its complete command
succeeds. Batfish publishes `profiled-batfish-success` only after schema-v4
verification, evidence/annotation publication, and cleanup succeed. CML publishes
`profiled-cml-success` only after the authoritative schema-v2 successful
lifecycle, annotation, and successful-evidence artifact upload. Failure publishes
no success receipt. Later steps consume bounded same-build metadata, never
Buildkite status APIs. No application converts failure to exit zero.

## Assurance

Batfish on `ncdp-validation` remains credential-free exact-four offline
candidate assurance: routed underlay, OSPF, VLAN and ACL. All 40 invariants and
full schema-v4 evidence remain authoritative; the concise human renderer is
unchanged. This fixed network assurance is not derived from the live
interface-description plan.

The single `cml-staging` job depends on validation and Batfish, runs on
`ncdp-staging`, and retains concurrency one in
`ncdp/cml-ephemeral-staging`. Its trusted hook, exact pipeline/queue/command
admission, nine protected environment names, staging JWT roles for 1/2/8/9,
17-resource Terraform ownership, one-shot CML lab START, transit-only recycle,
real service readiness, strict trust, and read-only validation are unchanged.
CML proves disposable device integration, not the proposed LIVE candidate.
Failure still preserves ambiguous state and a nonzero application result.
See the [staging runbook](buildkite-ephemeral-cml-staging-operations.md).

## Current schema-v2 delivery tail

The [deployment runbook](buildkite-profiled-delivery-operations.md) describes
agent-owned authority and artifact handling. This is not restored schema-v1
protected delivery or the historical cryptographic deployment JWT boundary.

1. `profiled-live-plan` on `ncdp-deploy` validates current profiled LIVE trust,
   uses current NetBox/OpenBao providers and read-only collection, and plans the
   fixed PR #132 target: device 1, core-02, interface 2/GigabitEthernet2.
   `deployments/live/profiled-demo.yaml` requests one interface description.
   An already-compliant target produces no plan, rather than fabricated work.
2. `profiled-promotion` on `ncdp-validation` independently downloads the exact
   same-build plan from its producer. The strict, self-digested
   `ProfiledPromotion` schema-v2 binds build UUID, commit, change, target/device,
   current plan digest, byte-level artifact hash, all validation receipts and
   both assurance digests. Legacy schema-v1 is rejected. Its annotation exposes
   the exact plan and promotion digests before the block.
3. `profiled-human-authorization` is a real fieldless block. It remains visible
   after soft-failed promotion; unblock authorizes only this build/promotion.
4. `profiled-deploy` on `ncdp-deploy` independently verifies canonical non-PR
   main/retry-zero/checkout identity, exact block DAG and Buildkite unblocker
   UUID, same-build downloads, manifest, plan/artifact/digests, all receipts,
   fixed current write projection and LIVE trust before device access. Only then
   it invokes current `ncdp profiled-deploy --plan ... --approve-digest ...`
   with `--report-json`, `--netbox --openbao --live`, once.
   Fresh CLI preflight, stale-plan and current-state checks remain authoritative.
   Invalid authorization emits NO WRITE and exits nonzero.
5. `profiled-deployment-evidence` validates a same-build schema-v2
   `ProfiledChangeRecord` when available, showing outcome and actual execution/
   recovery attempts. Missing artifacts are not fabricated evidence or proof
   that no write occurred; inspect retained state before a new attempt.

The CLI write projection remains devices 1/2 only; this automation narrows it to
one device-1 target. Devices 8/9, B4 service changes, fleet deployment and SNMP
provisioning remain write-denied. No automatic recovery/replay is added.

## Trust and acceptance limits

Buildkite metadata/artifact provenance, the exact scheduler block dependency,
reviewed canonical main and the single-user agent host are trusted personal-lab
boundaries. These receipts and the unblocker environment are **not** a new
cryptographic workload identity, signed attestation, or production isolation.
Buildkite administrators or compromised trusted main/agent code can undermine
them; they are not a replacement for independent production authorization.

Historical schema-v1 ADRs and acceptance remain historical. ADR 0027's proposed
hard merge-gate policy is superseded for this workflow. Real acceptance of the
corrected CML start/performance path and new main delivery tail remains PENDING;
local fake tests and a successful aggregate cannot establish it.
