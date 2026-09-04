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
  -> fresh complete preflight
  -> one profile-bound vendor transaction
  -> independent post-write observation
  -> immutable ProfiledChangeRecord
```

Fleet membership never implies write capability. The exact managed population
is stable NetBox devices 1, 2, 8, and 9 through
`ncdp-profiled-inventory` plus `PROFILED_POPULATION_CATALOG`. The current
interface-description operation admits only:

- `cat8000v_iosxe`: SSH/22, Cisco Ansible `network_cli`, and a frozen targeted
  inverse;
- `vjunos_router`: NETCONF/830, an exclusive candidate, commit-confirmed five
  minutes, independent observation, and explicit confirmation.

The `iosv_159_3_m12` and `iosvl2_2020` profiles remain exact-four managed
members but fail before secret or transport access for this operation. No
routed-underlay, OSPF, VLAN/trunk, ACL, or SNMP device-write authority is added.

## Planning and approval

`profiled-plan` resolves the exact Git-owned profiled subject, admits the
operation before interface or credential access, resolves stable interface
identity, rejects protected interfaces, binds the stable-ID OpenBao reference,
and collects current state through the profile-bound read-only adapter. It
creates a schema-v2 plan only when the target is not already compliant. The
artifact is create-only, mode `0600`, digest-bound, and secret-free.

`profiled-deploy` accepts only schema-v2 plans, validates canonical approval
syntax before external access, requires the exact plan digest and explicit
`--live`, validates the profiled LIVE trust generation, and reserves create-only
evidence before execution. Fresh preflight repeats subject, endpoint, profile,
operation, stable interface, credential-reference, protection, hostname, and
current-description checks. Any changed reviewed binding is stale; provider
inability is blocked.

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
accepted. They are not current runtime paths. Their typed artifacts and
historical ADR/acceptance evidence remain valid and parseable, but no current
CLI, script, or pipeline step can execute them. Any future protected delivery,
profiled fleet rollout, or disposable staging requires a new profiled design
and separate review.

The active Buildkite network assurance surface is the credential-free profiled
four-device PR Batfish step. Buildkite has no current device-write step.
