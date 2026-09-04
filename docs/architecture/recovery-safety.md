# Recovery safety

## Purpose and scope

The baseline recovery contract covers immediate, vendor-aware handling during
one active deployment attempt for the supported interface-description vertical.
It preserves the approved plan, provider-specific transaction semantics, fresh
independent observations, and honest final outcomes. It does not claim
multi-device atomicity or provide a historical rollback subsystem.

## Cisco targeted inverse

Planning freezes the observed previous interface description together with the
exact execution artifact. A Cisco plan also contains the digest-bound targeted
inverse for that same interface: restore the exact previous description, or use
`no description` when the property was previously absent. The transaction
strategy is `cisco_targeted_inverse`; neither execution nor recovery is derived
again at deployment time.

A known execution failure is final for that attempt. NCDP does not retry it and
does not issue a speculative recovery write. An ambiguous execution is also
never retried or followed by an automatic second write; a bounded read-only
observation may aid investigation without resolving the ambiguity dishonestly.

After known execution success, a fresh independent collection must confirm the
expected device and interface. Collection failure or identity mismatch stops for
operator investigation without speculative recovery. Only an identity-matching
read that observes a description other than the approved desired value makes
the exact frozen inverse eligible. NCDP executes that artifact once and performs
another independent read. `RECOVERED` requires that fresh observation to match
the exact previous description. Known recovery failure, ambiguous recovery, or
failed/mismatched recovery verification produces `RECOVERY_FAILED` or
`RECOVERY_AMBIGUOUS` as applicable and never triggers another write.

## Junos commit-confirmed recovery

Junos uses one exclusive candidate transaction for deterministic XML load,
commit-check, semantic candidate validation, and `commit confirmed 5`. A fresh
session independently validates the active result. Successful validation permits
one explicit confirmation of the pending commit.

If independent post-validation fails or the transaction cannot be closed safely,
NCDP deliberately leaves the temporary commit unconfirmed. The bounded native
commit-confirmed rollback remains the expected recovery mechanism, and the
workflow may report `AUTO_ROLLBACK_PENDING`. It does not issue a synthetic
inverse transaction.

If validation succeeds and explicit confirmation is attempted, a known failed
confirmation is `CONFIRMATION_FAILED` and an uncertain confirmation result is
`CONFIRMATION_AMBIGUOUS`. Confirmation is not retried and neither outcome causes
a synthetic inverse. `CONFIRMATION_AMBIGUOUS` does not establish whether the
temporary commit was confirmed, remained pending, or later rolled back.

An ambiguous commit-confirmed execution itself is not retried, confirmed, or
manually rolled back by the workflow.

## Historical fleet exposure

The retired schema-v1 fleet engine advanced only when a child outcome was
exactly `SUCCEEDED`.
Every other result stops later exposure, including `RECOVERED`, ambiguity,
failure, staleness, and blocking outcomes. A recovered canary demonstrates that
its device-level inverse was verified; it does not authorize the next canary or
wave. Previously successful members are not automatically reverted, remaining
members stay untouched, and partial outcomes are reported without claiming
fleet-wide atomic rollback.

## Approval and later rollback

Immediate recovery remains transitively bound to the same immutable schema-v2
plan and approval that authorized the active deployment attempt. No Buildkite
or fleet orchestrator broadens that authority.

A problem discovered later is handled as a new reviewed desired-state change:
Git review, validation, schema-v2 profiled planning, exact digest approval,
explicit local deployment, and independent validation apply again. `git revert`
may propose restoration of reviewed intent, but a Git operation alone never
authorizes a device write.

Automated change ancestry, historical state reconstruction, inverse-plan
generation, later-change conflict detection, and rollback-specific deployment
workflows are explicitly deferred. Configuration history and durable audit
records belong to Increment 10 rather than this recovery baseline.

## Limitations

The implemented recovery guarantees apply only to the narrow managed
interface-description property and its currently supported Cisco IOS XE and
Junos providers. They are not full-configuration replacement, a generic inverse
engine, device-wide rollback, fleet atomicity, or proof that recovery itself
cannot fail. Provider or transport uncertainty remains an operator-investigation
condition and is represented honestly in evidence.

The Cisco targeted inverse assumes that no out-of-band actor independently
changes the managed description between the known-successful execution and the
immediate validation/recovery window. This reference-lab baseline has no
cross-system or device-wide lock and no compare-and-swap ownership mechanism
against arbitrary external writers.
