# Profiled intent delivery acceptance

## Acceptance and evidence boundary

**CAP-INTENT-DELIVERY — ACCEPTED.** The user explicitly accepted the merged
implementation and controlled acceptance evidence after review.
Passing tests and merge did not confer acceptance; explicit user sign-off did.
The [capability ledger](../roadmap.md#cap-intent-delivery--intent-selected-generic-delivery)
is authoritative for state; the [intent contract](../architecture/intent-delivery.md)
defines behavior.

Implementation merged through [PR #151](https://github.com/Atheer-Kareem/network-change-delivery-platform/pull/151).
Acceptance used clean `main`, equal to `origin/main`, at
`67fb65478337dd53879b20b2f1ca16d335866d22`, and natural main
[Build 439](https://buildkite.com/atheer-kareem/network-change-delivery-platform/builds/439),
UUID `01a080f0-ebcb-4e49-873d-d0ef5779f123`.
This document records that reviewed session; no runtime operation was repeated
for the documentation closeout.

CAP-INTENT-DELIVERY is accepted. Protected main delivery reads one fixed
committed typed intent, resolves its logical target through the managed
population, and binds that intent independently through planning, promotion and
deployment authorization. The current real core intent remains unchanged and
safe on main, while merged exact offline proof demonstrates the same
control-plane path for already write-admitted vJunos without target-specific
branches. Human authorization remains fieldless, IOSv/IOSvL2 remain write-denied,
and credential, Batfish, CML and rollout boundaries remain unchanged.

A LIVE Junos write is not required to prove that committed intent selects an
already write-admitted target. The alternative-target property is established
by merged exact control-plane tests; real main runtime acceptance proves that
the same merged machinery safely preserves the protected production path.
This capability concerns selection and binding; it does not introduce a new
Junos transaction mechanism, which was already admitted and tested separately.

## Accepted flow and committed source

```text
fixed reviewed committed InterfaceDescriptionIntent
→ exact Git/NetBox target resolution
→ profile/operation admission
→ immutable plan or typed COMPLIANCE
→ intent-bound schema-v2 promotion when a plan exists
→ fieldless human authorization
→ independent intent/plan/promotion revalidation
→ deployment
```

Intent selects target. Target does not grant write authority. Managed membership
does not grant write authority. Human unblock does not select target.
One active intent selects one explicit device/interface; no fleet semantics were
accepted. COMPLIANCE creates no promotion or deployment authority.

Runtime acceptance used the unchanged fixed file
[`deployments/live/profiled-demo.yaml`](../../deployments/live/profiled-demo.yaml):

```yaml
change_id: CHG-PROFILED-LAB-DEMO
kind: interface_description
target: core-02
interface: GigabitEthernet2
desired:
  description: managed-by-ncdp-profiled-demo
```

The loader requires a bounded regular file at that repository-relative source,
with parent/final no-follow handling, exactly one YAML document, and rejection
of duplicate mapping keys and unknown fields. There is no environment path
selector, Buildkite metadata target selector, human-block target selector,
fallback or default target. The logical target must be Git-declared. The active
core intent remaining unchanged is reviewed data, not control-plane coupling.

The semantic binder requires exact intent/result equality for change ID,
operation/kind, logical target, interface name and desired description. Typed
plan/compliance models independently own their applicable stable device and
interface identities, profile, NOS, endpoint, credential provenance and observed
state. The plan additionally binds operation admission, transaction strategy and
execution preconditions. Logical target selection itself is not authorization;
COMPLIANCE claims no transaction or write.

## Promotion and historical compatibility

`ProfiledPromotion` remains **schema v2** with unchanged serialized field set and
canonical shape. The former literal/default restrictions for
`CHG-PROFILED-LAB-DEMO`, `core-02` and `netbox:dcim.device:1` were replaced with
bounded required values. Promotion derives change ID, target and stable device
identity from the validated exact plan and verifies the target/device pairing
against the Git population. A valid pairing alone grants no write authority;
operation admission remains plan/profile-owned.

The pre-capability core promotion fixture still parses as schema v2, reproduces
its original bytes exactly, preserves its canonical fields and calculates the
same digest:

`sha256:4aac9415f7c4856985e957158718a72a743c9b507827fc0476116a544a4d7d54`

No historical artifact migration or rewrite occurred.

Current interface-description admission remains:

| Automation profile | Write admission |
|---|---|
| `cat8000v_iosxe` | Admitted |
| `vjunos_router` | Admitted |
| `iosv_159_3_m12` | Denied |
| `iosvl2_2020` | Denied |

CAP-INTENT-DELIVERY generalizes selection among already write-admitted targets.
It does not broaden profile write eligibility. IOSv/IOSvL2 expansion remains
CAP-PROFILE-REUSE-WRITE.

## Merged offline acceptance proof

The focused merged acceptance suite passed **380 tests**.

An alternative Cisco core intent used a different safe change ID, admitted
interface and description through the same planning, promotion and authorization
machinery, without a demo tuple branch.

An alternative committed-style Junos intent for
`edge-junos-01 / netbox:dcim.device:2` proved the same generic control-plane path:

```text
intent → plan → promotion → authorization → simulated typed execution
→ durable EXECUTION → exact byte verification → temporary AuditStore round trip
→ chronology child/receipt → final evidence
```

No Junos-specific Buildkite target branch was introduced. No LIVE Junos write
occurred. Both Cisco and Junos COMPLIANCE tests preserved no-plan, no-promotion,
no-execution and no-chronology semantics.

This closes the former promoted-Junos representability boundary.
`ProfiledDeliveryAuditRecord` remains **schema v1** around schema-v2 delivery
artifacts. The offline Junos EXECUTION proof correlated the intent target,
stable device 2 and interface, plan digest and exact plan bytes, promotion
identity/digest, validation/Batfish/CML assurance digests, fieldless human
provenance, execution/plan binding, credential provenance, durable target,
exact artifact-byte hashes, AuditStore readback and chronology child.
This is representability and offline execution evidence, not LIVE Junos
EXECUTION runtime acceptance.

Current chronology retains the generic mapping
`netbox:dcim.device:N → netbox-device-N`. The Junos child/receipt proof preserved
`causality = NOT_PROVEN`. No independent-history contract changed and no real
Oxidized history was manufactured.

Merged negative tests rejected:

- Unknown targets, IOSv/IOSvL2 selection, protected interfaces and unsupported kind.
- Intent/result mismatch and changes to target, interface, desired description
  or change ID after promotion.
- Validly rehashed mismatched planning results and promotion tampering,
  including target/device mismatch, plan digest, plan artifact-byte digest,
  build/commit and validation/Batfish/CML digests.

Rejected cases establish no device writer authority. Changing only the unblocker
UUID cannot select a different target; it remains provenance for the
already-minted promotion.

## Real main Build 439

| Correlation | Value |
|---|---|
| Build | `439` |
| Build UUID | `01a080f0-ebcb-4e49-873d-d0ef5779f123` |
| Commit | `67fb65478337dd53879b20b2f1ca16d335866d22` |
| Branch/source | `main`, natural webhook build |

No duplicate build was triggered. All engineering stages passed, and all
**13 validation receipts** matched build/commit/step. Batfish **PASSED**.
Real disposable CML staging **PASSED**, with **4/4 READY**, **4/4 read-only
validation**, successful required recycle, cleanup, independent absence
verification and state retirement.

Planning and promotion/decision passed. Human authorization, deploy and final
delivery evidence remained **BLOCKED / NEVER STARTED**; human continuation was
**NO**. Buildkite reported the aggregate build as passed despite the blocked
delivery tail. Build 439 did not exercise deployment promotion or write authority.

### Real planning result: COMPLIANT

- Observation: `2026-09-08T12:29:58.160209+00:00`.
- Target: `core-02 / netbox:dcim.device:1`.
- Interface: `GigabitEthernet2 / netbox:dcim.interface:2`.
- Current and desired descriptions both: `managed-by-ncdp-profiled-demo`.
- Compliance digest:
  `sha256:38ab96eaeaf7d434661fccafdc47a45de1dfa0e95ddfe90cc2960a31459f2d7c`.
- Exact planning JSON-byte digest:
  `sha256:6a12f629ac40307fd9d4a0907bd1c0b77879614af8ebf6b50318691a4627e0ad`.

The typed result matched the committed intent, same-build planning publication
receipt and exact byte hash. The planning annotation derived change, target,
stable device, profile, interface name/identity, current/desired description,
operation and compliant state from that result. It displayed no transaction
strategy. No deployment plan existed, no promotion was minted, no deployment
authorization existed, no device command or recovery ran, and no chronology was
required.

Artifact REST listing/download was unavailable during acceptance. Verification
used retained exact planning JSON compared against the published same-build
exact byte hash. No direct artifact API download is claimed.

## Protected authority and assurance preservation

The installed protected hook matched merged source and retained canonical
repository, main-only, non-PR, retry-zero, exact commit, clean checkout, exact
queue, step/command and pipeline-binding checks. The human block remained
fieldless, and the authority graph was unchanged:

```text
profiled-live-plan → profiled-promotion → profiled-human-authorization
→ profiled-deploy → profiled-deployment-evidence
```

Deploy role/policy source remained byte-identical through the capability.
Permitted device credential reads remained exactly devices **1 and 2**;
devices **8/9** remained unavailable. The installed dedicated source was
preserved. No OpenBao policy/role modification or credential rotation/reissuance
occurred. Acceptance did not perform a live OpenBao policy query.

Batfish remains the existing **B4 D1 prerequisite**, not proof of the exact
selected interface-description candidate. Promotion binds its same-build success
digest when a real plan exists. No Batfish topology/invariant change occurred;
CAP-OP-ASSURANCE remains **DEFERRED**.

CML remains realization/integration assurance. It does not apply or rehearse the
selected interface-description write. Real main staging remained mandatory and
passed; the PR/development CML exception remains **ACTIVE**. No candidate-specific
staging write was added.

## Evidence and device preservation

| Preservation check | Result |
|---|---|
| Human continuation | NO |
| Device configuration writes | ZERO |
| Deployment command | NOT INVOKED |
| Historical AuditStore records | 11 → 11 |
| Current profiled records | 1 → 1 |
| Current chronology children | 0 → 0 |
| Checked AuditStore file hashes | 62 unchanged |
| Historical evidence mutation | NO |

No acceptance evidence was fabricated. No runtime, infrastructure or device
mutation was performed during this documentation closeout.

## Remaining capability boundaries

These were not accepted as part of CAP-INTENT-DELIVERY and are not started here:

- **CAP-PROFILE-REUSE-WRITE — USER APPROVED:** interface-description admission for
  IOSv/IOSvL2 through existing reusable profiles.
- **CAP-PROFILED-ROLLOUT — USER APPROVED:** multiple selected targets, selectors,
  canaries, waves and rollout execution.
- **CAP-OP-ASSURANCE — DEFERRED:** exact operation-bound assurance.
