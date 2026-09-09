# Rollout authorization and pre-execution admission

CAP-PROFILED-ROLLOUT Increment 4 established these reusable admission APIs.
Increment 5 composes them in [protected execution](profiled-rollout-execution.md);
the admission APIs and historical artifact bytes remain unchanged.
The capability remains **IN PROGRESS**. See the
[planning/promotion runtime checkpoint](profiled-rollout-runtime-planning.md#increment-3-runtime-checkpoint).

## Fieldless authorization

`ProfiledRolloutAuthorization` is a distinct frozen, extra-forbid schema **v1**.
It binds build UUID, source commit, change ID, parent semantic/exact-byte digests,
promotion semantic/exact-byte digests, ordered selected stable devices, canaries,
waves, human unblocker UUID and its own digest. Selected devices and cohorts are
derived frozen facts, never fields offered to a human. There is no target,
interface, description, profile, credential-scope or comment/options input.
Changing the unblocker changes provenance; it cannot choose a different target.

`authorize_rollout()` explicitly calls `verify_rollout_promotion()`. This
reconstructs the expected promotion from exact publication/parent bytes,
independently loaded committed intent, source commit, current Git expansion,
static protected credential decisions, all 13 same-build engineering receipts,
and Batfish/CML success digests. Both supplied promotion metadata digests must
match. Parsing a self-digested detached promotion is insufficient. A positive
all-COMPLIANT parent cannot mint promotion or authorization.

The verifier is pure: no NetBox, secret read, device collection or reservation.
It is not itself a Buildkite step. The protected caller must independently
establish canonical clean checkout and fieldless scheduler unblocker provenance;
typed artifacts and self-digests alone are not authenticated human decisions.

## Complete fresh preflight

`preflight_profiled_rollout()` first re-verifies the authorization against the
original approval inputs, before invoking any provider. It then:

1. Resolves and validates the complete current Git-declared managed population.
2. Expands the current committed instructions and rejects changed membership or
   order before selected-member activity.
3. Reuses the planner's complete member admission: exact device/interface,
   population agreement, profile/operation, protection and independent credential
   authority. Every selected member is admitted before child credential work.
4. Compares selected resolved facts, provenance and credential decisions with
   the approved parent. Resolves every exact credential reference, then loads
   every credential before the first device observation.
5. Reuses the existing child planner with the admitted inventory and already
   loaded credentials. Each child owns its fresh observation timestamp.
6. Compares every fresh child execution basis and returns one typed positive
   preflight only if the whole population passes. Any exception returns no
   positive record; no partial population is accepted.

Execution-basis comparison retains all child semantic fields except the
observation timestamp (`created_at` or `observed_at`) and corresponding child
self-digest. It therefore compares logical/stable device and interface identity,
profile/platform/NOS, endpoint/hostname, operation and transaction/recovery,
protection, exact credential reference, desired and current description,
preconditions and exact forward/frozen-inverse artifacts. The resolved device
and credential-admission models are compared independently, including CML/profile
and protection facts. New timestamps are expected; new state is not.

DEPLOYABLE → COMPLIANT, COMPLIANT → DEPLOYABLE, or a different pre-write current
description invalidates approval. Changed selected membership/order, a newly
matching Git member, removed member, identity, endpoint, profile, operation,
protection or credential decision also fails closed. Unselected membership is
not included in the frozen digest, but complete population admission still applies.

`ProfiledRolloutPreflight` is a new frozen schema **v1**, binding parent,
promotion and authorization digests, each ordered child's approved artifact and
result digests, execution-basis digest and fresh timestamp. It explicitly records
no execution. Preflight evidence is neither promotion nor authorization and
confers no execution permission by itself. All-COMPLIANT has no execution preflight.

## Local stable-device reservations

`reserve_rollout_devices()` uses nonblocking process-held `fcntl.flock` locks in
an owner-only external state root's `profiled-rollout-reservations` directory.
The root and subdirectory must be owned by the current user, mode 0700 and free
of symlink traversal. Lock files are regular, owner-only 0600, empty, single-link
files opened with no-follow handling. Unsafe retained state is rejected.

Keys are exact stable NetBox **device** identities, including COMPLIANT members;
hostnames, addresses and interfaces are not reservation identities. Acquisition
uses sorted stable-identity order. Duplicate/empty input is rejected. Conflict
fails the whole acquisition and releases earlier locks. All descriptors close
on normal result or exception, and process exit releases kernel locks. Persistent
empty unlocked files are not active reservations.

Authorization acquires zero reservations. Protected execution enters this
context only after human authorization and immediately before complete preflight,
then retain it through the protected device activity. No lock spans the human
pause. This is local overlap admission, not distributed locking, cross-host
atomicity or a fleet transaction.

Increment 5 integrates this same primitive into both protected single-target
and rollout execution after authorization, alongside the shared Buildkite
concurrency group. Real runtime overlap acceptance remains subject to review.

## Exact child bytes and remaining execution gates

Protected child execution receives the exact `child.artifact_bytes()` frozen in
the approved parent. Reserializing a parsed child and claiming equivalent bytes
is not permitted. Existing rollout parent v1/v2, child v2, rollout promotion v1
and single-target promotion v2 schemas/bytes are unchanged.

Whole-population preflight does not replace each child's fresh JIT prewrite
validation immediately before its one permitted forward invocation. No writer,
transaction, recovery, AuditStore execution or chronology persistence is called
by these APIs. Tests trap existing mutation boundaries and exercise local locks
only in temporary directories.

Protected execution composition is documented separately. Runtime evidence and
explicit user acceptance remain pending. Earlier successes are never automatically
rolled back, and uncertain writes are never retried.

Batfish/CML assurance meaning is unchanged. CAP-OP-ASSURANCE remains DEFERRED;
the temporary PR/development CML exception remains ACTIVE.
