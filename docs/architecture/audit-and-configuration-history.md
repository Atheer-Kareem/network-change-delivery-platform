# Audit and configuration history

## Purpose and boundary

The audit architecture correlates the bounded evidence that NCDP already
produces. It does not replace those artifacts with one large payload, make an
audit store an intent authority, or turn observed device configuration into
desired state. Git remains the authority for reviewed intent, NetBox for stable
inventory identity, OpenBao for credentials, and devices for observed reality.

Increment 10 is divided deliberately:

- 10A defines this evidence, correlation, storage, and sensitivity contract.
- 10B-1 implements the durable correlation record and append-only store;
  10B-2 integrates the protected Buildkite boundary and bounded queries.
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

Increment 10B-1 implements this contract in `audit.py` and `audit_store.py`:

- an explicit agent/operator-owned absolute root outside every checkout;
- the root and store-managed child directories mode `0700`, record and artifact
  files mode `0600`, with current-UID ownership and symlink checks; arbitrary
  ancestors such as `/Users` are not part of this permission boundary;
- one canonical JSON artifact per immutable object;
- for intrinsically digested plans, plan assurance, and promotion manifests,
  store identity equals the model's verified digest; for `ChangeRecord`,
  `FleetChangeRecord`, and `StagingEvidence`, it is SHA-256 over their complete
  canonical JSON;
- content-addressed artifacts at
  `artifacts/<reviewed-kind>/<sha256-hex>.json`;
- direct stable record lookup at `records/<record-id>.json`, preventing one UUID
  from appearing in multiple date partitions without introducing an index;
- exclusive create-new behavior and no silent overwrite;
- a 4 MiB maximum canonical artifact and 256 KiB maximum audit record;
- write to an exclusively created mode-0600 temporary inode in the destination
  directory, flush and `fsync`, publish with a same-directory hard link, then
  `fsync` the directory; `link()` returns `EEXIST` rather than replacing an
  existing destination;
- readers ignore incomplete temporary files and validate schema and digest;
- referenced artifacts are persisted before the final envelope, so no visible
  record points to a half-written artifact;
- a persistence failure fails closed and must not claim durable audit success.

`AuditArtifactKind` admits only `DeploymentPlan`, `FleetDeploymentPlan`,
`PlanAssuranceRecord`, `DeploymentPromotionManifest`, `StagingEvidence`,
`ChangeRecord`, and `FleetChangeRecord`. `AuditArtifactReference` binds kind,
schema version, digest, canonical store-relative locator, and size. It cannot be
used as a label for arbitrary JSON. Exact existing content-addressed artifacts
may be reused only after their regular-file metadata, canonical schema, size,
and integrity are revalidated. A corrupt or divergent collision fails closed.
A `ChangeAuditRecord` UUID collision always fails, even when existing bytes are
identical.

`AuditStore.persist_record()` validates the envelope digest and reads and
verifies every referenced artifact before publishing the record.
`read_artifact()` and `read_record()` enforce containment, regular non-symlink
files, owner and mode, size, exact schema version, canonical bytes, and digest.
10B-1 deliberately added no CLI, search, Buildkite, deployment, staging, or
device-workflow integration.

The envelope's canonical digest is its integrity identity; `record-id` is its
stable lookup identity. Both are recorded. Two records with the same content
remain explicit attempts rather than silently overwriting one another.
Buildkite may upload a sanitized convenience copy, but artifact retention is
never the durable authority and runtime evidence never enters the product Git
repository.

10B-2 adds `ncdp audit show <record-id>` and an exactly-one-filter
`ncdp audit find` by change ID, exact commit, Buildkite build UUID, or stable
NetBox device identity. Find validates every durable record, scans at most
10,000 records, returns at most 100 summaries by default and by hard limit, and
fails rather than returning incomplete results when either bound is exceeded.
Final-record corruption, symlinks, non-canonical names, and unexpected entries
fail the whole query; only `.audit-tmp-*` incomplete publication entries are
ignored. Artifact payloads are never printed by normal query output. Secondary
indexes or a database require measured scale or concurrency evidence.
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

## Protected Buildkite assembly and failure domains

10B-2 assembles one `ChangeAuditRecord` only in the existing main-only,
single-device `deploy-gate`. Its record UUID is exactly the immutable Buildkite
deployment-job UUID, so repeated publication in one prohibited retry context
collides while a new build/job is a distinct attempt. `BUILDKITE_REPO` is
normalized from reviewed GitHub SSH or HTTPS clone forms; commit and pipeline,
build, job, number, and step identities come from the validated Buildkite
environment. The record states only that `deployment-approval` was passed and
does not claim approver identity.

The gate downloads `staging-evidence/staging-run.json` specifically from the
same build's `cml-staging` step. Before it is durable, the application requires
matching pipeline, build, commit, main branch, staging step and `bk-<build-id>`
run identity, plus successful creation, readiness, NCDP validation, direct
destroy, independent absence, state retirement, and no primary or cleanup
failure. Existing promotion verification remains authoritative for the exact
manifest, single-device plan, PASSED plan assurance, artifact hashes, commit,
and their mutual digests. A produced `ChangeRecord` must agree with every
duplicated plan identity and property before publication.

An unchanged commit-bound live request is independently proven with the
existing Git-object contract and produces `NO_WRITE` evidence containing only
the plan, assurance record, promotion manifest, staging evidence, and envelope.
Absence of `ChangeRecord` alone never implies `NO_WRITE`. A real attempt adds
the semantically correlated `ChangeRecord`; its detailed outcome remains
authoritative and the envelope uses a total reviewed summary mapping.

The current single-device outcome mapping is explicit: `COMPLIANT` maps to
`NO_WRITE`; `SUCCEEDED` to `SUCCEEDED`; `RECOVERED` to `RECOVERED`; `BLOCKED`
and `STALE_PLAN` to `BLOCKED`; `AMBIGUOUS`, `RECOVERY_AMBIGUOUS`, and
`CONFIRMATION_AMBIGUOUS` to `AMBIGUOUS`; and `EXECUTION_FAILED`,
`POST_VALIDATION_FAILED`, `RECOVERY_FAILED`, `AUTO_ROLLBACK_PENDING`, and
`CONFIRMATION_FAILED` to `FAILED`. A newly introduced `FinalOutcome` has no
default path and requires an explicit mapping review.

`NCDP_AUDIT_STORE_ROOT` is required and `AuditStore` plus all same-build audit
inputs are validated before the second device-capable JWT, credential read, or
possible write. After a typed device outcome, durable artifacts publish first
and the envelope last. An audit failure then fails the Buildkite job but never
retries execution, invokes recovery, or changes Cisco/Junos transaction
semantics. When deployment and audit both fail, deployment remains the primary
outcome and both domains are reported. A failure before typed `ChangeRecord`
exists fabricates no durable execution record.

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

### Append-only observation correlation

Increment 10C-1 adds offline contracts and persistence only. A schema-1
`ConfigurationObservationRecord` is a separate follow-up correlation record,
not delivery evidence and not an `AuditArtifactKind`. Existing schema-1
`ChangeAuditRecord`, `ChangeRecord`, `FleetChangeRecord`, artifact kinds,
canonical bytes, digests, and `records/` paths remain unchanged.

Observation records are stored at
`observation-records/<observation-record-id>.json` under the same validated
external root. Before publication, the observation store reads the parent
through `AuditStore`, proves the exact parent UUID and digest, and proves the
stable NetBox device is a parent target. The parent is never rewritten, and
multiple immutable observation records may reference it.

Each record contains bounded repository, stable node, optional group, request,
timestamp, status, sanitized failure-category, and Git commit/path/blob
metadata. It contains no configuration bytes, diffs, command or API output,
credentials, tokens, or free-form error text. At least one pre- or
post-observation is required. Successful changed/unchanged claims require
complete, internally consistent revision metadata; failures and timeouts cannot
fabricate an after revision.

The relationship may describe temporally bracketed, post-only, or uncorrelated
pre-only evidence. `TEMPORALLY_BRACKETED` records an ordered pre/post pair that
the future controller establishes around the parent attempt; it deliberately
does not treat the parent envelope's `generated_at` as a device-execution
boundary. Schema-1 causality is fixed to `NOT_PROVEN`: temporal and object
correlation cannot establish exclusive causation. Oxidized remains
observed-state chronology only and cannot authorize deployment, recovery, or
rollback. Runtime installation, private Git history, inventory/credential
materialization, scheduling, API control, and protected pre/post integration
remain future 10C work.

### Reproducible observation runtime

Increment 10C-2 packages Oxidized 0.37.0 and oxidized-web 0.18.1 in the
project-controlled OCI runtime frozen by ADR 0016. Ruby, Bundler, the complete
gem graph, and the multi-platform base image are exact inputs. The final image
runs as a fixed non-root user and retains runtime libraries rather than its
native build toolchain.

Rugged 1.9.6 supplies its vendored libgit2 1.9.6 in this image. Runtime version
and native-linkage inspection established that `rugged.so` does not dynamically
use Debian system libgit2, so the runtime carries no separate system-libgit2
dependency.

The packaging acceptance is intentionally synthetic: one TEST-NET identity is
loaded with polling disabled, `GET /nodes.json` reports that it has never been
collected, and Docker publishes the web listener only on host loopback. No
device connection, configuration output, NetBox or OpenBao access, private Git
history, or persistent service is part of this increment. Inventory and
credential materialization, external Git output, scheduling, forced collection,
and reboot-persistent ownership remain later 10C work.

### Authority source materialization

Increment 10C-3 keeps both authority APIs outside the collector. The NCDP host
materializer resolves the complete active `ncdp-managed` NetBox population and
loads exact-path credentials through a dedicated OpenBao AppRole, then
atomically publishes one private JSONFile runtime cache. Oxidized reads that
file and contacts neither NetBox nor OpenBao.

The initial allowlist is exactly NetBox device IDs 1 and 2; stable Oxidized node
names derive from those object IDs, and device 3 is a fail-closed population
error. IOS XE maps to `ios`, Junos maps to `junos`, and both collector endpoints
use SSH port 22. The Junos transactional NETCONF port 830 is not reused.

The cache is credential-bearing but is not authority or evidence. Publication
uses private owned directories and an atomic complete-file replacement. Failed
refresh leaves the previous bytes untouched while returning failure. Whether a
future persistent service may use stale cache remains deferred, as do device
collection and Git chronology.

## Implementation sequence and limitations

10B-1 provides the typed envelope/reference models and append-only store.
10B-2 adds protected Buildkite assembly, pre-write store validation, honest
post-outcome persistence failure semantics, and bounded `show`/`find` reads
without migrating execution schemas or adding Oxidized.

10C-1 adds typed append-only observation correlation without an Oxidized
runtime. 10C-2 adds only the reproducible non-root OCI package and bounded
synthetic API proof. Later 10C increments should add the private persistent
Oxidized service, Cisco and Junos models,
NetBox-to-node mapping, OpenBao credential boundary, bounded forced collection,
and Git reference correlation. It must not change desired-state authority or
place full configurations in NCDP audit JSON.

Baseline limitations remain explicit: current evidence was not designed as one
transaction across systems; Buildkite artifact retention is not durable audit
storage; approver identity is unavailable at the current boundary; existing
execution records are not self-digested; the current deployment context does
not expose a trustworthy built-container digest; and an Oxidized collection
cannot always prove one-to-one causality or create a new commit when the
configuration is unchanged. The filesystem store narrows races with a private,
owned root, no-follow checks, inode metadata checks, exclusive temporary files,
and no-replace hard-link publication. It does not claim protection from a
privileged hostile local actor or eliminate every check/use race on platforms
without directory-handle-relative reads. If directory durability fails after
linking, it attempts to remove its new final link before returning failure; an
unclean process or filesystem failure may still leave an ignored temporary
entry or require operator inspection.
