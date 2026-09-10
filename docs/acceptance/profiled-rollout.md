# Profiled rollout acceptance

## Acceptance decision and scope

CAP-PROFILED-ROLLOUT — Bounded profiled multi-target rollout is **USER
ACCEPTED**. The user explicitly accepted the implemented capability after review
of the successful controlled runtime evidence, the preceding fail-closed runtime
evidence and the offline fault-injection coverage recorded below. Implementation,
merge and passing tests alone did not confer acceptance.

This acceptance applies to the current schema-v2 profiled rollout path for the
reviewed four-device personal-lab population. It preserves exact frozen scope,
fieldless authorization, complete preflight before writes, sequential canary/wave
exposure, current vendor-specific child transaction semantics, independent final
validation and durable parent/child evidence. It makes no fleet-wide atomicity,
automatic rollout rollback, retry or resume claim.

## Positive runtime evidence — Build #472

Canonical-main [Build #472](https://buildkite.com/atheer-kareem/network-change-delivery-platform/builds/472)
ran build UUID `01a08b20-7e5c-4d84-907f-076f5740fd49` at commit
`e1c7b393edcf048ba9369ac5872c953017fcd092` for change
`CHG-PROFILED-ROLLOUT-20260910-R3`. The controlled run established:

| Evidence | Accepted result |
|---|---|
| Engineering validation | 13/13 receipts |
| Batfish assurance | 40/40 |
| Disposable CML | Real CML PASS 4/4 |
| Rollout authorization | Fieldless; `sha256:dda846a2507ca8ca4887f1840462ba4b113f42c3b30aaa3feb422882d1bf787c` |
| Complete preflight | PASS; `sha256:dc097688a9c658590264e1d9bf4e6e2cc37fbd1ec394c36e7296e8e260b1085e` |
| Frozen execution order | `1 → 2 → 8 → 9` |
| Child outcomes | All four `SUCCEEDED`; one forward invocation per child |
| Final whole-population validation | `PASSED`; `sha256:4baade0c083ddf9266fa74799d6ca55710e19cfbc153bf7c37798f685d5744aa` |
| Durable parent | UUID `01a08b20-95e0-4e54-8ef5-546b4e722639`; `sha256:64a678e3c8419db933ccb23730fa2047f81cbec9f1ea4fcc4887d5476eeab2a4` |
| Evidence completion | `child_evidence_complete = true`; `evidence_failed = false` |
| Chronology | `TEMPORALLY_BRACKETED`; causality `NOT_PROVEN` |

The Cisco children used the admitted targeted transaction behavior. The Junos
child used commit-confirmed and was explicitly confirmed only after the required
successful observation. Every child reused its exact approved bytes, and the
parent durably bound the complete child evidence. The run performed no retry,
replay or fleet-level rollback and makes no fleet-wide atomicity claim.

The single-target human block was also continued, contrary to the preferred
procedure for this run. That continuation was nevertheless compliant:
`execution_attempted=false`, and it produced no device write. The rollout then
performed its own independent fresh complete preflight and passed it, so the
single-target continuation did not invalidate the R3 rollout evidence.

## Negative runtime safety evidence

### Build #468 — stale frozen rollout

Canonical-main Build #468 began from a frozen rollout that became stale after a
separately authorized state change. The protected consumer verified authority,
then complete preflight stopped the rollout before child execution. There were
zero rollout child writes and no retry or replay. This is accepted evidence that
an earlier valid authorization does not override a changed execution basis; it
is not a successful rollout execution.

### Build #470 — incomplete prerequisites

Canonical-main Build #470 experienced a host sleep/connectivity interruption and
therefore produced incomplete engineering evidence. Assurance-prerequisite
admission stopped rollout planning before any rollout authority or write was
created. The build was not retried or resumed. This is accepted evidence that
incomplete engineering prerequisites fail closed; it is not a successful
rollout execution.

## Offline fault-injection review

Dangerous failure paths were deliberately reviewed through offline
fault-injection tests rather than manufactured on LIVE devices. The reviewed
coverage establishes:

- complete preflight failure creates zero child executions;
- reservation conflict causes no provider activity;
- escaping or uncertain child execution produces `STOPPED` or `PARTIAL` and no retry;
- a just-in-time stale child receives no forward invocation;
- `EXECUTION_FAILED`, `AMBIGUOUS` and `RECOVERED` each stop later exposure;
- Junos confirmation `FAILED`, `AMBIGUOUS` or `AUTO_ROLLBACK_PENDING` stops before waves;
- chronology failure stops exposure at the appropriate boundary;
- child or chronology evidence failure causes no replay or later exposure;
- final validation failure causes no rollout-level rollback; and
- tampering with original child bytes is rejected.

**No unsafe LIVE failure was manufactured solely for acceptance.**

## Preserved boundaries

The temporary PR/development CML exception remains **ACTIVE** and byte/behavior
unchanged. It did not weaken Build #472 because canonical non-PR `main` consumed
real same-build CML evidence. Its existing exit condition still requires
restoration before FINAL INTEGRATED refinement-roadmap acceptance; restoration
is separate follow-up work and is not part of this acceptance change.

CAP-OP-ASSURANCE remains **DEFERRED**. This acceptance neither promotes nor
implements operation-bound service assurance. No device, CML, NetBox, OpenBao,
AuditStore, hook, Buildkite job or other live infrastructure was accessed or
changed by this documentation closeout.
