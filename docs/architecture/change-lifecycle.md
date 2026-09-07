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
  -> immutable schema-v2 plan
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

## Planning and approval

`profiled-plan` resolves the exact Git-owned profiled subject, admits the
operation before interface or credential access, resolves stable interface
identity, rejects protected interfaces, binds the stable-ID OpenBao reference,
and collects current state through the profile-bound read-only adapter. It
creates a schema-v2 plan only when the target is not already compliant. The
artifact is create-only, mode `0600`, digest-bound, and secret-free. Compliant
planning produces no deployable plan and therefore no promotion authority;
current downstream no-change presentation remains CAP-OUTCOME-TRUTH work.

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
through the current private delivery state and Buildkite artifact path. They do
not yet connect to durable AuditStore, PRE/write/POST correlation or the viewer.
The accepted record's provider-derived `execution.changed == false` does not
represent its independently observed before/post transition. CAP-OUTCOME-TRUTH,
CAP-DURABLE-EVIDENCE and CAP-CONFIG-CHRONOLOGY own those refinements; historical
records are not rewritten.
