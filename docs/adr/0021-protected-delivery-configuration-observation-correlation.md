# ADR 0021: Protected delivery configuration-observation correlation

## Status

Accepted for implementation in Increment 10C-7A; live acceptance requires
Increment 10C-7B after merge.

## Decision

Schema-1 `ChangeAuditRecord` remains the immutable protected-attempt parent and
schema-1 `ConfigurationObservationRecord` remains an append-only sibling child.
One no-retry `deploy-gate` job validates authorization, captures a successful
PRE observation, invokes the device attempt, and immediately attempts POST.
POST is attempted even when the device command returns nonzero. A PRE failure
blocks execution.

The adapter derives the Oxidized node only from the verified promoted plan and
the exact commit-bound live request. Successful transient observations map to
the existing CHANGED or UNCHANGED status; reviewed failures map only to closed
failure categories. Private mode-0600 attempt files in the job's mode-0700
temporary directory carry canonical metadata between CLI invocations. They
contain no configuration, diff, credential, or free-form exception text.

Child persistence occurs only after the parent has been published. It derives
the parent UUID from the current Buildkite job, re-reads the parent and its
canonical digest, and revalidates Git commit, pipeline/build/job/step,
approval, change, target, interface, credential provenance, and typed
ChangeRecord membership. It never scrapes the parent digest from logs or
rewrites the parent. The child relationship is `TEMPORALLY_BRACKETED` and
causality remains schema-fixed `NOT_PROVEN`.

The bracket requires PRE completion no later than POST request and successful
POST must begin from PRE's exact path-scoped after revision. Repository HEAD is
irrelevant. The selected live demonstration additionally expects POST CHANGED
and a distinct blob, but that expectation is not a global schema invariant.

Configuration bytes and diffs remain only in private Oxidized Git. Audit or
observation persistence failure never causes device retry, rollback, or a
second transaction. The device outcome remains primary. Operator CML lifecycle
stays outside Buildkite: the planning twin is destroyed before PR CI, and after
merge a fresh trusted twin must be prepared before approving only the exact new
main build. Final live acceptance retires trust and destroys that twin.

Build #150 exposed an operational regression before PRE: recreation of the
reboot-persistent deploy agent omitted the already accepted external Ansible
collection path while leaving that runtime intact. The protected gate now
requires the exact external path before retaining its existing offline
manifest/version verification. It never installs from Galaxy or falls back to
checkout-local collections. Build #150 performed no device write and is not
retriable; comment-only retry authorization 1 prepares a distinct commit-bound
attempt with the same immutable plan.

Build #152 then verified that corrected runtime and reached PRE, where it failed
closed because the required post-merge operator twin, realization-anchored host
trust, and schema-2 collection readiness had not been prepared before approval.
It submitted no collection or device transaction, created no audit evidence,
and is permanently non-retriable. Comment-only retry authorization 2 prepares a
new commit-bound attempt with the same immutable plan. Its fresh operator twin,
trust, and readiness must be established after merge and before explicit
approval of only that new main build. Final live correlation acceptance remains
pending.

Build #154 passed authorization, runtime, realization trust, and schema-2 PRE
readiness, then submitted exactly one successful Cisco PRE collection. The
fresh realization created a legitimate third private-history commit one second
after upstream `node.last.end`, within ADR 0020's accepted serialization
tolerance. Durable conversion incorrectly used that upstream end as observation
`completed_at`, so schema validation rejected the later Git timestamp before
the device-capable OIDC request or deployment. No device write, parent audit,
or observation child occurred, and Build #154 is permanently non-retriable.
Durable completion now means the later metadata-settlement boundary; validation
remains strict and the five-second chronology bound is unchanged. Comment-only
retry authorization 3 prepares another distinct commit-bound attempt with the
same immutable plan.

## Consequences

10C-7A can prove orchestration, conversion, correlation, privacy, persistence,
and failure behavior offline and prepare a commit-bound change. It cannot claim
real protected pre/write/post acceptance. That evidence belongs to 10C-7B
after user merge and explicit approval of the new merged-main build.
