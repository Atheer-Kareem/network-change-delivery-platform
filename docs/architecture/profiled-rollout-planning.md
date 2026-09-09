# Profiled rollout planning foundation

CAP-PROFILED-ROLLOUT is IN PROGRESS under its unchanged [approved
contract](../roadmap.md#cap-profiled-rollout--bounded-profiled-multi-target-rollout).
Increments 1 and 2 supply a read-only Python API, immutable planning artifacts
and composable closed Git-population selector clauses.
Increment 3 adds [protected planning and parent promotion](profiled-rollout-runtime-planning.md).
There is no rollout CLI, human authorization or execution path.
The active single-target intent and current child commands remain unchanged.

```text
reviewed explicit members and/or selector clauses with exact operation payloads
→ full Git-declared managed population resolution
→ deterministic expansion + source provenance + overlap rejection
→ exact selected device/interface resolution and independent admission
→ current schema-v2 child planning for every selected member
→ exact child bytes/results + frozen canaries/waves
→ versioned profiled rollout PLAN OR COMPLIANCE
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

Reviewed explicit-member order is material. Inputs are frozen,
extra-forbid models, bounded to 100 members, bounded change/interface names and
existing bounded logical names/descriptions. Only `interface_description` is
admitted. Closed selector predicates govern membership; each clause supplies its
reviewed operation payload. Arbitrary selector/query expressions remain rejected.
There is no environment, free-text query, discovery or human-block selector.
The API accepts reviewed data from its caller; it does not establish Git checkout
or human authorization provenance. The protected sibling runtime independently
loads fixed reviewed Git input; the
read-only planning API itself does not confer checkout or human authority.

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

Increment 3 defines the static protected device set `(1, 2, 8, 9)` in repository
policy and a `ProtectedRolloutCredentialAuthority` decision provider. Actual
child secret availability remains independent. Explicitly approved external
OpenBao/hook activation is now [verified](profiled-rollout-runtime-planning.md#verified-post-review-activation);
offline tests alone grant no live access. Rollout execution does not exist.

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
NetBox query. Every clause must match at least one member. OR alternatives may
be filtered out by another dimension: roles `[core, edge]` AND NOS `[iosxe]`
validly selects core alone. Zero-match clauses fail the whole operation.

`ProfiledRolloutSelectionIntent` contains `explicit_members` and `selectors`,
both defaulting to empty tuples, with at least one source required.
Each `ProfiledRolloutSelectorClause` binds a closed selector, one exact interface
and one exact desired description. The selector chooses **who**; its reviewed
clause supplies **what** for every match. Interface names and descriptions are
never inferred from profile, inventory or device facts. A missing or protected
interface on any expanded member blocks all child collection.

Expansion order is fixed:

1. Explicit members in their reviewed order.
2. Selector clauses in their reviewed order.
3. Each clause's matches in Git population declaration order.

Any repeated logical target, including explicit/selector or selector/selector
overlap, is rejected without deduplication. Expansion and overlap checks occur
after complete population admission and before selected-member resolution,
credential-authority decisions, child secret reference/load or collection.
`ProfiledRolloutExpandedMember` freezes source kind (`explicit` or `selector`),
zero-based source index, target, interface and desired description. The index
identifies the explicit member or selector clause in the reviewed instruction.

A new nonmatching managed member leaves the bounded result/digest unchanged when
selected facts, decisions and explicit timestamps are identical. A newly matching
Git member expands the clause with its reviewed payload and requires independent
member, interface, operation and credential admission. Successful replanning
produces a different parent; the old frozen artifact does not expand itself or
authorize the new member. NetBox-only discovery never adds a member.

## Exact parent versions and readback

Merged Increment-1 `ProfiledRolloutIntent`, `ProfiledRolloutPlan` and
`ProfiledRolloutCompliance` retain their exact explicit-only **v1** shape.
They reject selector fields, including an explicit null selector. Golden hashes
captured from merged Increment 1 verify unchanged PLAN and COMPLIANT bytes and
digests. The new selection intent with only explicit members also emits these
exact v1 artifacts.

Any selector or mixed-source planning emits **v2** through
`ProfiledRolloutPlanV2` or `ProfiledRolloutComplianceV2`. V2 binds the reviewed
selection instructions, exact expansion/provenance, selected-only Git facts,
existing exact child bytes/results, policy and cohorts. The selected-only
population snapshot retains Git declaration order without including unselected
managed members. It lets readback reproduce each clause and validate provenance
and payload against the frozen children. This is artifact consistency, not proof
of current external authority: planning still admits the full population first.

`read_profiled_rollout()` dispatches exact schema-version/result-type pairs.
Unknown versions/types and duplicate JSON keys fail. V1 cannot consume v2
selector content, even if its version label is changed. No historical bytes are
reinterpreted. Changing selector instructions changes the v2 parent digest even
when the current selected members happen to remain identical. Reordered or
altered expansion/provenance must agree exactly with the bound instructions.

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

Both parent versions belong to the current profiled planning namespace; neither
revives historical schema-v1 fleet plans or executors. Existing child schema v2
and all historical schemas/bytes remain unchanged.

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
`ProfiledRolloutCompliance` (v1) or `ProfiledRolloutComplianceV2`, retaining every
exact child compliance artifact.
It has no plan, promotion, execution, recovery or chronology requirement. It
cannot be parsed as a rollout PLAN.

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
