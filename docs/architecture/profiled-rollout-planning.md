# Profiled rollout planning foundation

CAP-PROFILED-ROLLOUT is IN PROGRESS under its unchanged [approved
contract](../roadmap.md#cap-profiled-rollout--bounded-profiled-multi-target-rollout).
Increments 1 and 2 supply a read-only Python API, immutable planning artifacts
and an optional closed Git-population selector.
There is no rollout CLI, promotion, authorization, execution or Buildkite path.
The active single-target intent and current child commands remain unchanged.

```text
reviewed ProfiledRolloutIntent with explicit operation payloads
→ full Git-declared managed population resolution
→ optional closed selector + exact ordered payload agreement
→ exact selected device/interface resolution and independent admission
→ current schema-v2 child planning for every selected member
→ exact child bytes/results + frozen canaries/waves
→ ProfiledRolloutPlan OR ProfiledRolloutCompliance
```

## Selection and independent authority

`plan_profiled_rollout()` accepts a typed intent and caller-owned read-only
inventory, credential-authority, secret and collection providers. It first
validates the complete resolved `ProfiledInventoryPopulation`. Every selected
logical target must match its Git declaration and its independently resolved
NetBox device exactly. Stable interfaces must belong to their exact device and
match the reviewed interface name; inventory-owned protection is enforced.
Duplicate device/interface identities, unknown members, ambiguous resolution and
unsupported operations block the whole operation.

Without a selector, reviewed intent order is material and determines selected
order. Inputs are frozen,
extra-forbid models, bounded to 100 members, bounded change/interface names and
existing bounded logical names/descriptions. Only `interface_description` is
admitted. The optional closed selector below governs membership only; arbitrary
selector/query expressions remain rejected.
There is no environment, free-text query, discovery or human-block selector.
The API accepts reviewed data from its caller; it does not establish Git checkout
or human authorization provenance. That protected integration is pending.

Each member independently needs managed membership, the current explicit
operation/profile catalog entry, and a positive `RolloutCredentialAdmission`
from the injected `RolloutCredentialAuthority`. The decision binds an authority
identity, exact stable device and exact OpenBao credential reference, with no
credential values. It records availability for planning, not a persistent grant.
A copied decision or self-digested artifact cannot replace future caller-owned
credential and deployment checks.

```text
managed membership != protected credential authority != operation authority != rollout authorization
```

The live dedicated Buildkite configuration remains `DEVICE_IDS = (1, 2)`.
Tests use explicit synthetic decisions for 1/2/8/9; they do not grant or claim
protected-main access to devices 8/9. The reviewed expansion belongs to later
protected-runtime integration.

## Increment 2: closed population selection

`ProfiledRolloutSelector` is frozen and extra-forbid. Its only optional dimensions
are tuples of existing closed enum values:

| Dimension | Existing enum | Current vocabulary |
| --- | --- | --- |
| `operational_roles` | `OperationalRole` | core, edge, transit, access |
| `network_oses` | `NetworkOS` | iosxe, ios, junos |
| `automation_profile_ids` | `AutomationProfileID` | cat8000v_iosxe, vjunos_router, iosv_159_3_m12, iosvl2_2020 |

At least one dimension is required. Each supplied tuple is nonempty and unique.
Matching is fixed: **OR within a dimension, AND across dimensions**. No match
mode, NOT, expression tree, regex/glob, free-text platform/type filter, arbitrary
field/query, NetBox filter or environment interpolation is accepted. Selector
value order cannot choose execution order.

Selection evaluates only the ordered Git `ProfiledPopulationDeclaration`
associated with the fully admitted `ProfiledInventoryPopulation`. It adds no
NetBox query. The result must be nonempty, and every supplied enum value must
participate in at least one final result member. Contradictory predicates and
values discarded by another dimension fail; they are not silently ignored.

The selected logical-name sequence must equal `intent.members` exactly in
**Git declaration order**. No union, missing/extra payload or reordered member
list is allowed. A selector selects **who**, never **what**: every target still
requires its own reviewed interface and desired-description payload. This check
occurs after full population admission and before any selected-member resolution,
credential-authority decision, child secret reference/load or collection.

A new nonmatching managed member does not change this bounded result or digest
when selected facts, decisions and explicit timestamps are identical. A new
matching member expands the selector result and rejects the old intent before
child activity because its reviewed payload is absent. Population growth cannot
automatically create rollout authority.

The complete supplied selector is canonical parent content through the typed
intent. A different dimension, value combination or explicit/selector mode changes
the parent digest even if current matching members are identical. Unselected
population remains admission context outside the digest. Readback also verifies
that selector predicates and participating values agree with frozen child facts;
that local consistency check cannot establish complete current membership. The
planning boundary must resolve the whole caller-owned population independently.

`selector=None` (including an omitted selector) retains explicit-only behavior.
The optional field is omitted from serialization when None, preserving the exact
Increment-1 canonical shape, bytes and digests. Golden hashes captured from
merged Increment 1 cover both PLAN and COMPLIANT artifacts. Current profiled
parent schema v1 and child schema v2 remain unchanged; selector-bearing artifacts
use the newly supported optional field. No historical evidence is rewritten.

## Current child lifecycle reuse

All selected members are resolved and admitted before any child credential load
or observation. The service constructs existing `InterfaceDescriptionIntent`
objects using the rollout change ID and each exact target/interface/description.
It invokes the existing `plan_profiled_change()` with the admitted inventory
snapshot; child protection, profile-local admission, credential reference,
collection, observed identity and forward/inverse artifact rules remain there.
No renderer, collector, writer or recovery algorithm is forked.

Every child must return exactly one schema-v2 `ProfiledDeploymentPlan` or
`ProfiledComplianceRecord`. Failure of any member raises without returning or
publishing a parent. Earlier read-only observations are not partial rollout
approval. Missing results and simultaneous plan/compliance results are errors.
No provider in this layer exposes a writer/deployer method.

## Exact bytes and immutable parent

`ProfiledRolloutChild` retains the original serialized UTF-8 child JSON verbatim,
its SHA-256 byte digest, its independent canonical child result digest, selected
resolved device/interface facts, operation admission and credential decision.
Original bytes are available through `artifact_bytes()`. Readback hashes those
bytes directly, rejects duplicate JSON keys, validates the current typed child,
and compares child identity/profile/NOS/endpoint/reference/protection facts with
the frozen selection. It does not regenerate JSON to claim byte equality.

The new `ProfiledRolloutPlan` and `ProfiledRolloutCompliance` use schema v1 in
**their own new profiled planning namespace**. This does not revive historical
schema-v1 fleet plans or executors. Existing child schema v2 and all historical
schemas/bytes remain unchanged.

The parent canonical digest covers the source commit, entire typed intent and
policy, ordered children with exact JSON bytes and both digests, and frozen
cohorts. Semantic intent/result binding covers every supported child intent
field. Whitespace-only changes to child bytes change the parent digest even when
the child's semantic digest is unchanged. Reordering selection or changing a
child between DEPLOYABLE and COMPLIANT also changes or rejects the binding.
Deterministic equality requires identical input facts, decisions and explicit
observation timestamps. An explicit `created_at` override is validated before
provider access and passed to every child for deterministic tests. Normal planning
passes `created_at=None`: each existing child planner assigns its own timestamp
after that child's read-only observation. There is no parent observation timestamp.
The exact child artifacts bind these individual timestamps; a new observation
timestamp intentionally changes the artifact.

Full managed declaration is admission context, not parent content. Selected
resolved facts are frozen, but adding/changing an unselected managed member does
not change the bounded parent digest. Full-population admission must still pass.
Digests establish integrity, not approval; no artifact here grants write authority.

## Frozen canaries and waves

Policy carries an explicit bounded wave size and optionally reviewed canary
logical names. Without explicit canaries, the first deployable member in intent
order represents each distinct adapter/recovery family. This policy comes from
current child operation admissions, with no device/profile dispatch table.
Explicit canaries must be selected deployable members and cover all represented
families. If deployable cardinality exceeds family cardinality, at least one
member must remain for a wave; an explicit all-canary selection then fails.

Remaining deployable members retain intent order and are partitioned into finite
waves of the reviewed size. Parent validation requires the exact deterministic
canaries, waves and within-wave order. Every deployable member appears once;
COMPLIANT members appear in neither canaries nor waves. These are frozen planning
cohorts only, with no execution or dynamic redistribution.

An all-compliant population produces distinct positive
`ProfiledRolloutCompliance`, retaining every exact child compliance artifact.
It has no plan, promotion, execution, recovery or chronology requirement. It
cannot be parsed as `ProfiledRolloutPlan`.

## Remaining increments

Protected integration/credential expansion, promotion and fieldless
authorization, complete population preflight and fresh child prewrite
revalidation, overlap admission, canary/wave execution and stop semantics, final
whole-population validation, parent durable evidence/chronology and runtime
acceptance remain pending. Future execution must repeat caller-owned admission
and full preflight, preserve fresh
child prewrite checks, and stop later exposure on every non-SUCCEEDED child.
Nothing here weakens one-shot/uncertain-write semantics or introduces atomicity,
automatic rollback or revival of `fleet-plan`/`fleet-deploy`.

Batfish remains existing B4 prerequisite assurance and CML remains realization
and read-only integration assurance; neither rehearses the selected write.
CAP-OP-ASSURANCE stays DEFERRED and the temporary PR/development CML exception
stays ACTIVE. No roadmap capability beyond CAP-PROFILED-ROLLOUT is started.
