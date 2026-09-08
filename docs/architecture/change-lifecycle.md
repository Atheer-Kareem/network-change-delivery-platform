# Change lifecycle

The current ordinary change lifecycle is schema-v2 and profile-bound. Its only
operator-facing planning and execution commands are `ncdp profiled-plan` and
`ncdp profiled-deploy`. The legacy `plan`, `deploy`, `fleet-plan`,
`fleet-deploy`, SNMP provisioning-plan, and protected-promotion deployment
commands are retired; schema-v1 models remain only for historical artifact and
audit compatibility.

```text
reviewed interface-description intent
  -> exact profiled NetBox subject and operation admission
  -> exact profiled LIVE trust
  -> stable interface and OpenBao reference binding
  -> fresh read-only observation
  -> compliant observation (no plan/authority), OR immutable schema-v2 plan
  -> exact digest approval plus explicit --live
  -> exact effective Cisco collection-runtime verification (Junos independent)
  -> fresh complete preflight
  -> one profile-bound vendor transaction
  -> independent post-write observation
  -> immutable ProfiledChangeRecord
```

Population membership never implies write capability. The current proof population
is stable NetBox devices 1, 2, 8, and 9 through
`ncdp-profiled-inventory` plus `PROFILED_POPULATION_CATALOG`. The current
interface-description operation admits only:

- `cat8000v_iosxe`: SSH/22, Cisco Ansible `network_cli`, and a frozen targeted
  inverse;
- `vjunos_router`: NETCONF/830, an exclusive candidate, commit-confirmed five
  minutes, independent observation, and explicit confirmation.

The `iosv_159_3_m12` and `iosvl2_2020` profiles remain managed
members but fail before secret or transport access for this operation. No
routed-underlay, OSPF, VLAN/trunk, ACL, or SNMP device-write authority is added.

Protected main delivery selects the same typed intent from the fixed committed
`deployments/live/profiled-demo.yaml`. The [intent boundary](intent-delivery.md)
independently binds every supported intent field to the plan/compliance result
at promotion and deployment. The active intent still selects core-02; the same
control path also admits vJunos. Human authorization is fieldless and applies
only to the already-minted immutable promotion. Batfish/CML receipts remain
prerequisites, not exact description-candidate assurance or write rehearsal.

## Planning and approval

`profiled-plan` resolves the exact Git-owned profiled subject, admits the
operation before interface or credential access, resolves stable interface
identity, rejects protected interfaces, binds the stable-ID OpenBao reference,
and collects current state through the profile-bound read-only adapter. It
creates a schema-v2 plan only when the target is not already compliant. The
artifact is create-only, mode `0600`, digest-bound, and secret-free. Compliant
planning produces no deployable plan and therefore no promotion authority;
a successful comparable observation instead produces `ProfiledComplianceRecord`.
The CLI prints COMPLIANT and can save it with `--compliance-output`; `--output`
remains exclusively a real deployment plan. A failed planner produces neither.
The compliant record binds change/target, stable device/interface, platform/NOS/
profile/operation, endpoint/hostname, observed and desired description, OpenBao
reference (no secret), aware observation timestamp and canonical digest. Its
plan is null and promotion/execution/recovery flags are false. It cannot be
parsed as a deployment plan or grant write authority.

`profiled-deploy` accepts only schema-v2 plans, validates canonical approval
syntax before external access, requires the exact plan digest and explicit
`--live`, validates the profiled LIVE trust generation, and reserves create-only
evidence before execution. Fresh preflight repeats subject, endpoint, profile,
operation, stable interface, credential-reference, protection, hostname, and
current-description checks. Any changed reviewed binding is stale; provider
inability is blocked. Before preflight can load credentials or collect device
state, Ansible-backed admission invokes the retained exact runtime verifier
through the selected Cisco adapter and its effective Runner path. It verifies
pinned manifests/versions, not cryptographic collection contents. Junos skips it.

## Execution and recovery

Cisco executes the exact frozen artifact once. An ambiguous result is never
retried or recovered; at most one read-only reconciliation observation is
evidence. A targeted inverse is eligible only after known execution success,
exact post-write identity, and failure to observe the desired description. The
frozen inverse runs once and `RECOVERED` requires independent exact restoration
of the previous description.

Junos prepares one exclusive candidate, validates it and freezes the candidate
diff digest before one commit-confirmed attempt. It confirms only after an
independent exact observation of desired state. Commit or confirmation
ambiguity is never retried. Unsafe close or failed post-validation leaves the
temporary commit unconfirmed and reports `AUTO_ROLLBACK_PENDING`.

See [recovery safety](recovery-safety.md) for the complete outcome semantics.
Controlled PR #132 LIVE acceptance proved exactly the C8000V IOS-XE and vJunos
interface-description paths; it did not broaden the operation matrix. See the
[acceptance record](../acceptance/profiled-deploy-live-acceptance-pr132.md).

## B5 boundary

Interface descriptions are outside the current B5 managed envelopes.
`ProfiledChangeRecord.managed_state_acceptance_attempted` is always false; the
executor has no `ManagedStateStore` dependency and performs no D0 advancement.
Future writable B4 verticals must project fresh O′ into their exact envelope and
pass `compare_postwrite_to_d1()` plus
`build_postwrite_validated_evidence()` before accepted-state advancement.

## Retired delivery surfaces

The schema-v1 fleet engine, protected Buildkite delivery, and disposable
exact-two Terraform/CML staging were successfully engineered and historically
accepted. Their typed artifacts and historical ADR/acceptance evidence remain
valid and parseable, but the legacy execution engine and its current CLI,
script, and pipeline entry points have been removed. Profiled fleet rollout
still requires its approved new design. Current schema-v2 main delivery and its
real disposable staging prerequisite are demonstrated in the user-supplied
[current acceptance](../acceptance/profiled-main-delivery.md). Staging grants no
device-write authority.

The active Buildkite network assurance surface is the credential-free profiled
PR/main Batfish step followed on non-PR main by disposable CML read-only integration.
PR/development staging is temporarily skipped under the ACTIVE ledger exception.
The current main-only Buildkite tail wraps the same schema-v2 plan/deploy
boundary with immutable same-build promotion and a real human block. Commands
soft-fail only for presentation; missing validation/assurance/promotion still
prevents execution. PRs have no write tail. See [workflow](buildkite-workflow.md).

## Current evidence boundary

Schema-v2 plans, promotions and `ProfiledChangeRecord` artifacts are retained
through private delivery state and Buildkite artifacts. The Buildkite deploy
boundary additionally admits AuditStore and persists plan/promotion before its
single CLI invocation, then durably correlates typed execution evidence.
COMPLIANCE is durably published without a plan, promotion or execution record.
The existing viewer reads current envelopes; final Buildkite evidence consumes
only a same-build publication pointer. This integration is tested offline with
COMPLIANT durability runtime-accepted. Current chronology is implemented offline
under CAP-CONFIG-CHRONOLOGY (see below);
historical records are not rewritten. See the [publication contract](audit-and-configuration-history.md#current-buildkite-publication-integration).

### Provider metadata, observation and outcome

`execution.changed` and `recovery.changed` mean provider-reported mutation:
explicit boolean true/false is preserved; missing, censored or non-boolean
metadata is `null` (unknown). Disposition is classified independently. Missing
metadata neither fails execution nor implies that no mutation occurred.
`post_validation.changed` instead compares an independently observed description
with the reviewed/preflight description: true for a transition, false for the
same state, null when identity/state cannot be compared. It is never copied from
the provider. Older records may retain null observational metadata and the
previous adapter's false default; they are not rewritten.

Final success requires successful fresh preflight, attempted successful execution
and successful independent observation of desired state. Junos additionally
requires validated candidate/diff, commit-confirmed and successful confirmation.
Provider `changed=false` or `null` is compatible with SUCCEEDED and an observed
transition. Cisco ambiguous reconciliation remains AMBIGUOUS even when collection
succeeds; on that path `post_validation.succeeded` records collection success,
while `changed` requires comparable identity. It cannot authorize retry/recovery.
Recovery's `succeeded` retains the current lifecycle classification: provider
success can still yield RECOVERY_FAILED if restoration cannot be observed.

`ProfiledChangeRecord` rejects mismatched approval/plan digests, unattempted stages
with result facts, inconsistent pre/post observations, execution on blocked/stale
paths, ineligible recovery, Cisco records with Junos-only stages, and inconsistent
Junos candidate/confirmation outcomes. It preserves failed, ambiguous, recovery,
auto-rollback-pending and confirmation distinctions. These are consistency checks
of representable evidence, not independent proof of external device activity.

`verify_profiled_record_plan` revalidates both schema-v2 artifacts and compares all
duplicated approved bindings: change, digests, target/device/interface, platform,
NOS/profile/operation, endpoint/hostname, reviewed/desired descriptions, credential
reference and transaction strategy. Buildkite uses it before execution-record
publication and final rendering. Candidate diff is execution-time evidence, not
a duplicated plan value. No write is rebuilt or retried by this verification.

## Current profiled chronology boundary

`ProfiledChangeRecord` remains operation-specific lifecycle evidence. Independent
Oxidized metadata brackets the execution window with successful PRE and a POST
attempt. Exact PRE-after/POST-before binding is required for success; intervening
history is ambiguous. TEMPORALLY_BRACKETED with NOT_PROVEN causality never means
whole-config atomicity, candidate validation or exclusive NCDP causation.

CAP-CONFIG-CHRONOLOGY is implemented offline and remains IN PROGRESS pending
acceptance. See the [current chronology contract](audit-and-configuration-history.md#current-profiled-configuration-chronology).
