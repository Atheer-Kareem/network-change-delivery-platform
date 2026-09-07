# Profiled durable publication acceptance

## Acceptance and evidence boundary

**CAP-DURABLE-EVIDENCE — ACCEPTED.** The user explicitly accepted the capability
after review of controlled build 420 runtime evidence, the real local AuditStore
and the loopback viewer. The [capability ledger](../roadmap.md#cap-durable-evidence--durable-schema-v2-delivery-evidence)
is authoritative for its state; the [publication contract](../architecture/audit-and-configuration-history.md#current-buildkite-publication-integration)
defines the implementation.

COMPLIANT durable publication is runtime-accepted end to end.

EXECUTION durable publication remains comprehensively offline-validated and will
receive supplemental runtime evidence on the next legitimate network write. No
device change is required or should be manufactured solely for acceptance. This
is accepted capability scope, not incomplete acceptance.

Evidence was harvested from existing build 420's scoped API metadata, step logs
and annotations, retained original JSON bytes, typed AuditStore reads and the
real store's loopback viewer. Buildkite artifact downloads were unavailable to
the inspection credential; retained original bytes were independently verified
against the exact-byte hashes in Buildkite metadata. No build was triggered or
retried, no device queried, and no evidence rewritten during verification or
this documentation closeout. No credential reference or secret is reproduced.

## Run and planning identity

| Field | Verified value |
|---|---|
| Build | [420](https://buildkite.com/atheer-kareem/network-change-delivery-platform/builds/420) |
| Build UUID | `01a07d93-7fe6-4064-8533-f79f427b5cca` |
| Commit | `98cdf4d1b4161466624bf202aec4d27a6f89b608` |
| Branch | `main` |
| Change | `CHG-PROFILED-LAB-DEMO` |
| Target / stable device | `core-02 / netbox:dcim.device:1` |
| Interface / stable interface | `GigabitEthernet2 / netbox:dcim.interface:2` |
| Current description | `managed-by-ncdp-profiled-demo` |
| Desired description | `managed-by-ncdp-profiled-demo` |
| Change required | `False` |
| Outcome | `COMPLIANT` |
| Planning observation | `2026-09-07T20:45:34.499476+00:00` |

PR #145, commit `2e8c0422c3ce9d4d52dc8096b3fc2cbd2fbae6ea`, subsequently
changed only the Batfish icon in the pipeline label and annotation heading.
It did not change the durable-publication implementation exercised by build 420
and does not require another acceptance run.

## Delivery steps and zero execution

| Step | Result | Established evidence |
|---|---|---|
| `profiled-live-plan` | Passed, exit 0 | Successful compliant observation; change required `False`; no deployment plan |
| `profiled-promotion` | Passed, exit 0 | COMPLIANT decision; no promotion minted |
| `profiled-human-authorization` | Unblocked | Static continuation granted zero write authority |
| `profiled-deploy` | Passed, exit 0 | COMPLIANT result durably persisted and re-read; publication receipt emitted |
| `profiled-deployment-evidence` | Passed, exit 0 | Independently validated same-build planning result and durable publication receipt |

Three COMPLIANT annotations came from the decision, `profiled-deploy` and final
evidence steps. They describe **one planning observation and one durable
publication, not multiple deployments**. Planning emitted its own already-compliant
summary. Raw step logs and rendered annotations agreed on the required facts.

The typed compliance result has no plan and records execution/recovery attempted
and promotion minted as `False`. Retained run artifacts and the durable envelope
contain no `ProfiledDeploymentPlan`, `ProfiledPromotion` or `ProfiledChangeRecord`;
promotion metadata is absent. Logs, typed evidence and the reviewed compliant
early-return path establish that `uv run --frozen ncdp profiled-deploy` was not
invoked. No device writer ran. This conclusion is not inferred from artifact
absence alone.

Final evidence job `01a07d93-9eb3-4724-b420-3e2d2fd464ed` reported COMPLIANT,
write attempted `False`, recovery attempted `False`, promotion minted `False`,
the durable UUID/digest below and the exact planning observation time.
`Durable publication: NOT ESTABLISHED` appeared in neither its successful log
nor annotation. Downstream continuation made no fresh device-state observation;
the immutable compliance result describes the recorded planning time.

## Exact evidence identities

| Evidence | Verified identity |
|---|---|
| Compliance intrinsic digest | `sha256:610add8d6a688a57a29cb0b2f21cecc546312379e46dee9bd8b0263be914d311` |
| Original planning JSON-byte digest | `sha256:6e7bb13c6720a9c95ae6e11aacbb4073b9299e4ced2f1e74f5367b4f5652e048` |
| Deploy job / durable record UUID | `01a07d93-9eb1-4385-804c-c28bf81376d7` |
| Durable envelope digest | `sha256:7a8bb4f907df484dcf90378385c5372b36ce33b9b1495d3a006ce2becd4a312a` |
| Receipt self-digest | `sha256:2b914deab3fe4965e45f10794642737271d24e581a6561c7c0cf338a3864aea9` |
| Exact receipt-byte hash | `sha256:62a8d4564728bc414a7714aa7cd81cc1b5402a692096e40b29e80d4211caaab3` |

`ProfiledDurablePublicationReceipt` schema and self-digest validated, with exact
build/commit, deploy-job/record UUID, durable digest and COMPLIANCE / COMPLIANT
binding. Its exact original bytes match `profiled-durable-publication` metadata.
The reviewed publisher emits this receipt only after persistence and equal
typed readback. **AuditStore is durable correlation authority; the receipt is
only the same-build pointer.**

## Real store and viewer verification

Typed AuditStore APIs validated `profiled_delivery_audit_record`, its canonical
self-digest, COMPLIANCE / COMPLIANT outcome and exact Git/build/job/target
correlation. Credential provenance binding validated without printing its
reference. Authorization and assurance were absent. Exactly one referenced
artifact was `profiled_compliance_record`, with the intrinsic digest above;
there was no plan, promotion or execution artifact. Original planning-byte
hash and typed-content equality validated separately from canonical storage.

Historical durable records remained **11 → 11**, with pre-run historical
record/artifact bytes unchanged. Current profiled records increased **0 → 1**.

The bounded loopback viewer index and
`/profiled-records/01a07d93-9eb1-4385-804c-c28bf81376d7` displayed Current
profiled delivery, COMPLIANT, `NOT REQUIRED — COMPLIANT`, correct commit/build
and stable target, compliance artifact identity and original JSON-byte digest.
No authorization or assurance facts, credential reference, filesystem locator,
raw configuration or environment values were exposed. Loopback binding, CSP
and no-store headers validated; the temporary viewer was stopped afterward.
It correctly stated: `Current PRE/write/POST delivery correlation not connected yet.`
CAP-CONFIG-CHRONOLOGY remains USER APPROVED and was not started.

## Narrow caveat and unchanged boundaries

Build 420 had **`quality-observability-runtime exit 4`** while the aggregate build
passed. This record does not claim all engineering checks passed. The failure
does not invalidate CAP-DURABLE-EVIDENCE acceptance: the COMPLIANT path minted
no promotion, did not consume deployment-assurance prerequisites and makes no
claim that all assurance/engineering stages succeeded. Investigation and repair
are outside this closeout; no new capability or roadmap item is created.

Current promotion remains restricted to core-02/device 1. No write admission,
population, credentials, retry behavior or PRE/write/POST integration changed.
The temporary PR/development CML exception remains ACTIVE. Historical acceptance
records retain their original meaning and bytes.
