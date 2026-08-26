# Audit and configuration history

## Purpose and boundary

The audit architecture correlates the bounded evidence that NCDP already
produces. It does not replace those artifacts with one large payload, make an
audit store an intent authority, or turn observed device configuration into
desired state. Git remains the authority for reviewed intent, NetBox for stable
inventory identity, OpenBao for credentials, and devices for observed reality.

Increment 10 is divided deliberately:

- 10A defines this evidence, correlation, storage, and sensitivity contract.
- 10B will implement the durable correlation record and append-only store.
- 10C will add private Oxidized Git-backed actual-state chronology and bounded
  references from audit evidence.

## Existing evidence inventory

The current `ChangeRecord` is not the complete cross-pipeline change history.
It is bounded evidence for one device execution attempt. The following
inventory is the compatibility baseline for 10B.

| Artifact or evidence | Producer and scope | Integrity and sensitivity | Current location and lifetime | Future treatment |
| --- | --- | --- | --- | --- |
| Reviewed intent/change request | Git review; one device or fleet desired-state change | Exact Git commit identity; no credentials | Product repository, durable Git history | Reference repository, commit, PR when available, path, and intent identity |
| `LiveDeploymentRequest` | Protected deployment boundary; commit-bound authorization for one device change | Binds schema/action, change ID, plan digest, and inventory object ID; it does not itself bind assurance or promotion and currently does not authorize fleet deployment | Product repository, durable Git history | Reference the request path and its exact bound fields; correlate assurance and promotion separately through the verified promotion manifest and deployment-gate comparison |
| `DeploymentPlan` | Planner; one frozen device target and exact execution/recovery artifacts | Canonical SHA-256 digest; contains configuration commands and credential reference, but no credential value | Process/local file, reviewed Git fixture, or promotion bundle | Reference by digest and durable artifact identity; do not embed execution payloads |
| `FleetDeploymentPlan` | Fleet planner; frozen ordered targets, child plans, canaries, and waves | Canonical SHA-256 digest; embeds child plans | Process/local file or promotion bundle | Reference by digest; embed only a bounded target identity index when needed for queries |
| `SnapshotManifest` | Assurance snapshot preparation; exact file set and source kind | Canonical manifest digest; snapshot bytes may contain modeled configuration | Temporary checkout-local preparation | Reference the manifest digest; exclude snapshot bytes |
| `AssuranceEvidence` | Batfish assurance; frozen bounded observations, parse summaries, flow results, and invariants | Typed but has no intrinsic canonical digest field; no credentials | May be standalone local evidence in the older assurance path; embedded in `PlanAssuranceRecord` for plan assurance | When embedded, rely on the enclosing record; if persisted independently, bind its canonical/store bytes with the audit-store artifact SHA-256 |
| `PlanAssuranceRecord` | Plan assurance; plan-, policy-, derivation-, and snapshot-bound assurance evidence | Canonical and carries its own SHA-256 digest; `verify_digest()` validates it | Local mode-0600 JSON and promotion bundle | Reference its existing digest and outcome; retain the immutable record as the assurance artifact promoted by the current deployment path |
| `DeploymentPromotionManifest` and bundle | Promotion step; exact approved artifact inventory | Manifest is canonical and self-digested; each `PromotedArtifact` has size and SHA-256; no separate bundle digest exists | Buildkite artifact and build metadata; checkout copy is temporary | Reference the promotion/manifest digest and immutable promoted-artifact hashes; Buildkite retention is not durable authority |
| Buildkite deployment/staging contexts | Trusted job boundary; pipeline, build, commit, job, step, branch, queue, and retry identity | Application-validated and, for workload identity, OpenBao claim-bound; tokens are secret and excluded | Process environment only | Embed the stable non-secret identity fields |
| `StagingEvidence` | Ephemeral staging lifecycle; sanitized realization, readiness, validation, destroy, absence, and retirement results | Versioned bounded schema; artifact digest is calculated externally, not a model field | Checkout-local JSON uploaded as a Buildkite artifact; successful Terraform state is retired | Reference sanitized evidence digest and outcome; never ingest Terraform state or Day-0 data |
| `ChangeRecord` | Device workflow; one execution, validation, and immediate recovery attempt | Frozen versioned schema but not self-digested; contains credential provenance/reference, never values | CLI report or mode-0600 Buildkite deployment artifact | Preserve unchanged; persist as a separate immutable artifact and bind its canonical bytes with a store SHA-256 |
| `FleetChangeRecord` | Fleet workflow; one rollout attempt, preflight, stop history, final validation, and child results | Frozen versioned schema but not self-digested; embeds the fleet plan and child `ChangeRecord` objects | CLI report or caller-selected local artifact | Preserve unchanged; persist and reference as one immutable artifact rather than duplicating its children in the envelope |
| Buildkite metadata and artifacts | Promotion, staging, and deployment scripts; within one build | Digest-bound where the underlying model defines it; artifact retention is operationally bounded | Buildkite build lifetime; survives checkout deletion but is not permanent | Use to assemble and transfer evidence, then copy approved bounded artifacts to the durable store |
| Acceptance reports | Maintainers; reviewed summaries of live increments | Human-reviewed Git history, not a machine evidence schema | Product repository | Context only; not a durable execution authority |
| Ephemeral Terraform state | Terraform staging lifecycle; provider and credential-bearing realization state | Sensitive, including Day-0 copies | External run directory; retired after proven destroy or retained for recovery | Exclude completely |

Process-local inventory objects, interface observations, provider results,
preflight results, and planning wrappers remain useful inputs to the bounded
records above. They do not each require a new durable artifact.

## Top-level correlation record

10B should introduce a separate `ChangeAuditRecord`; it should not enlarge or
rename `ChangeRecord`. The new record is an immutable, versioned correlation
envelope for one reviewed change and delivery attempt. This preserves mature
device and fleet evidence semantics and avoids a migration that would turn a
device record into an unrelated pipeline object.

The envelope embeds only bounded correlation and summary fields:

- its schema version, record identity, creation time, and final outcome;
- NCDP change ID;
- repository identity, exact commit SHA, and PR identity when trustworthy and
  available;
- Buildkite pipeline ID, build ID and number, and relevant step/job identities;
- execution container/image digest when a trustworthy runtime boundary exposes
  it; current Git-pinned base-image digests are not proof of the resulting job
  image identity;
- stable NetBox device and interface object identities;
- credential source and reference, never a value or secret-bearing username;
- immutable plan and fleet-plan digests and frozen target identities;
- assurance, promotion, and sanitized staging outcomes and artifact references;
- the protected approval boundary that was passed;
- deployment attempt identity and bounded execution/fleet outcome summaries;
- optional Oxidized capture references once 10C exists.

A typed artifact reference carries artifact kind, artifact schema version,
SHA-256, and a store-relative locator. Large plans, full child records, modeled
snapshots, provider payloads, and configurations remain separate. For a single
device, the envelope references its `ChangeRecord`. For a fleet, it references
the `FleetChangeRecord`; the fleet record's existing embedded plan and child
records remain its compatibility boundary. A small device/outcome index may be
embedded in the envelope to support queries without copying execution detail.

The record must never contain passwords, password verifiers, SSH private keys,
credential usernames treated as secret material, JWTs, OpenBao or CML tokens,
NetBox tokens, Terraform state, secret-bearing Day-0 configuration, raw Ansible
Runner events, unbounded provider tracebacks, raw provider responses, or full
network configurations.

## Record identity and durable store

Baseline 1 needs an append-only external JSON store, not a database. The query
volume and access pattern do not yet justify PostgreSQL, Elasticsearch, or a
second service.

The store contract for 10B is:

- an explicit agent/operator-owned absolute root outside every checkout;
- root and parent directories mode `0700`, record and artifact files mode
  `0600`, with ownership and symlink checks;
- one canonical JSON artifact per immutable object;
- SHA-256 over canonical JSON with the object's digest field omitted;
- a content-addressed artifact layout such as
  `artifacts/<kind>/<sha256>.json`;
- a bounded record layout such as `records/<year>/<month>/<record-id>.json`,
  where `record-id` is a generated UUID, recorded once and thereafter stable;
- exclusive create-new behavior and no silent overwrite;
- write to a unique mode-0600 temporary file in the destination filesystem,
  flush and `fsync`, publish without replacement, then `fsync` the directory;
- readers ignore incomplete temporary files and validate schema and digest;
- referenced artifacts are persisted before the final envelope, so no visible
  record points to a half-written artifact;
- a persistence failure fails closed and must not claim durable audit success.

The envelope's canonical digest is its integrity identity; `record-id` is its
stable lookup identity. Both are recorded. Two records with the same content
remain explicit attempts rather than silently overwriting one another.
Buildkite may upload a sanitized convenience copy, but artifact retention is
never the durable authority and runtime evidence never enters the product Git
repository.

Initial reads can scan and validate the bounded record tree. The anticipated
interface is `ncdp audit show <record-id>` and `ncdp audit find` by change ID,
commit, Buildkite build ID, or NetBox device ID. Secondary indexes or a database
should be introduced only after measured scale or concurrency requires them.
Retention and deletion policy are deliberately outside 10B; append-only means
the baseline does not mutate or silently retire records.

## Authority and correlation rules

Stable identities are used wherever available:

- Git: repository identity and exact commit SHA; PR number/identity is
  additional review context, not a substitute for the commit.
- Buildkite: immutable pipeline and build IDs, build number for human lookup,
  and step/job IDs for staging and deployment attempts.
- inventory: NetBox object identities for devices and interfaces; display names
  and addresses are bounded context, not sole keys.
- plan: canonical device/fleet plan digest.
- assurance and promotion: their canonical record/manifest digests.
- CML staging: Buildkite-bound staging run ID and sanitized evidence digest;
  disposable CML UUIDs are useful realization context, not inventory identity.
- execution: references to existing `ChangeRecord` or `FleetChangeRecord`
  artifacts plus bounded final outcomes.
- observed configuration: Oxidized node mapping and Git commit/blob references,
  never desired-state ownership.

One audit record correlates these authorities; it does not reconcile or replace
them. Mutable titles, hostnames, addresses, and build numbers must not be the
only correlation keys.

## Human approval boundary

The current fieldless Buildkite block proves that the protected
`deployment-approval` dependency was unblocked before the deployment job.
Buildkite documents that a block pauses the build for an authorized team member
and that field values, when configured, are exposed through build metadata.
The current pipeline has no approval fields and the deployment process has no
broad Buildkite API credential. Therefore Baseline 1 may honestly record the
block key, `passed = true`, build/commit/promotion identity, and downstream
deployment job identity. It must not claim or infer the approver's personal
identity. Adding that authority is a separate reviewed decision. See the
[Buildkite block-step contract](https://buildkite.com/docs/pipelines/configure/step-types/block-step).

## Oxidized actual-state chronology

Oxidized belongs in 10C as a separate observed-state system. Upstream supports
IOS/IOS XE and Junos models, HTTP/CSV/database sources, and a Git output that
creates a commit when collected configuration changes. Its web API can move a
node to the head of the queue, fetch a node, list nodes, and inspect node
versions. The Git output uses Rugged/libgit2, so ordinary Git hooks do not run.
These capabilities make a persistent personal-lab container/service feasible,
with its configuration and Git repository mounted outside this source tree.
See the upstream [Oxidized README](https://github.com/ytti/oxidized/blob/master/README.md),
[output documentation](https://github.com/ytti/oxidized/blob/master/docs/Outputs.md),
[source API](https://github.com/ytti/oxidized/blob/master/docs/Ruby-API.md), and
[IOS](https://github.com/ytti/oxidized/blob/master/lib/oxidized/model/ios.rb) and
[Junos](https://github.com/ytti/oxidized/blob/master/lib/oxidized/model/junos.rb)
models.

NetBox should remain inventory authority. 10C should map each stable NetBox
device ID to one bounded Oxidized node identity through a read-only source or a
narrow generated adapter. NetBox must not become a credential store. Device
credentials remain OpenBao-managed and must be supplied only through a
protected Oxidized runtime boundary; the exact least-privilege account and
non-persistent injection mechanism require implementation-time validation.

After deployment, NCDP can request a bounded node fetch and observe the node's
Git history. The correlation reference should contain the NetBox device ID,
Oxidized node/group, private repository identity, Git commit SHA, configuration
path/blob hash, capture request and observation times, and outcome. A collection
that observes no content change may correctly yield no new Git commit; it must
reference the unchanged commit/blob and say so.

The API request, timestamps, and before/after repository state provide useful
correlation, but periodic collection and concurrent external changes mean they
do not by themselves prove that one NCDP write caused one Git commit. 10C must
serialize and poll bounded collection, record that limitation, and avoid
fabricating exact causality unless upstream behavior or a verified integration
provides it.

Actual configurations remain potentially sensitive even when Oxidized secret
filters are enabled. The private persistent Git repository stays outside this
public repository, is not uploaded wholesale to Buildkite, and is not printed
in logs or copied into `ChangeAuditRecord`. Only non-secret commit, path, blob,
time, node, and outcome metadata cross the audit boundary. Oxidized records
observed actual state; Git/NCDP remains desired-intent authority.

## Implementation sequence and limitations

10B should add only the typed envelope/reference models, canonical digest,
append-only external JSON store, validated read/query boundary, and Buildkite
deployment correlation needed to persist sanitized existing evidence. It should
not migrate current execution schemas or add Oxidized. If assembling a complete
record and adding CLI queries is too large after implementation discovery, split
10B into model/store first and pipeline/query integration second.

10C should add the private persistent Oxidized runtime, Cisco and Junos models,
NetBox-to-node mapping, OpenBao credential boundary, bounded forced collection,
and Git reference correlation. It must not change desired-state authority or
place full configurations in NCDP audit JSON.

Baseline limitations remain explicit: current evidence was not designed as one
transaction across systems; Buildkite artifact retention is not durable audit
storage; approver identity is unavailable at the current boundary; existing
execution records are not self-digested; the current deployment context does
not expose a trustworthy built-container digest; and an Oxidized collection
cannot always prove one-to-one causality or create a new commit when the
configuration is unchanged.
