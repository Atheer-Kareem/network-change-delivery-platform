# Junos interface-description vertical

## Common intent and authority

Increment 4 extends the existing vendor-neutral interface-description intent to
Junos. Git remains authoritative for the desired description. NetBox owns device
and requested-interface identity, the NETCONF endpoint, platform, eligibility,
and protection tags. OpenBao resolves the static lab credential from stable
NetBox device identity.

Junos uses NETCONF port 830 with no fallback. Every fresh PyEZ connection requires
the exact operator-established `[host]:830` entry in the current user's standard
`known_hosts`, verifies host keys, supplies the OpenBao username/password, and
disables SSH key, agent, proxy-command, and user SSH-config routing fallback.

Read-only discovery uses structured `get-interface-information` operational data
as the authority for physical-interface existence and admin/oper state. Committed
interface configuration is retrieved separately and overlays only configured
description, family-inet addresses, and explicit disable state. An unconfigured
physical port therefore still exists, while a configuration-only or logical-unit
name cannot establish physical existence. `fxp0` and `em0` are independently
protected as management interfaces in Python in addition to NetBox protection
tags. PyEZ and ncclient failures are normalized at the adapter boundary; raw
RPC replies and third-party exception details never enter workflow evidence.

## Candidate transaction

Transactional configuration uses direct PyEZ under Python policy, as decided in
[ADR-0005](../adr/0005-junos-transaction-execution-boundary.md). Cisco remains on
Ansible Runner. One exclusive candidate session performs, in order:

1. prove the shared candidate has no uncommitted difference;
2. load only deterministic typed XML for the requested interface description;
3. run commit-check;
4. inspect the exact candidate interface subtree and bounded candidate diff;
5. require the diff to be non-empty and scoped only to the approved interface;
6. issue `commit confirmed 5` through that same `Config` object.

Exclusive locking is never stolen. If preparation fails after load but before a
commit attempt, rollback 0 discards only NCDP's uncommitted candidate. Rollback 1
is never used. The immutable plan binds the XML artifact, transaction strategy,
fixed five-minute timeout, and confirmation contract.

The bounded diff validator recognizes only the known-safe representation of a
description change under an existing interface or creation of the one typed
interface stanza containing that description. Any other representation fails
closed and must be validated against the lab before a first write. Evidence
retains only the candidate diff SHA-256, never the raw diff or candidate.

## Validation, confirmation, and honest outcomes

Known commit-confirmed success closes the transaction session. Independent
post-validation opens a fresh PyEZ/NETCONF session and verifies hostname,
interface identity/existence, and exact desired description. A failure is
`AUTO_ROLLBACK_PENDING`: NCDP sends no confirmation or other write and does not
claim recovery before later independent observation.

Transaction cleanup is phase-aware. Before a commit-confirmed attempt, cleanup
or unlock failure blocks with a bounded error. After an attempt, neither Config
unlock nor the enclosing Device/NETCONF session close can replace a known failed
or ambiguous disposition. If the temporary commit was known successful but
either close fails, NCDP does not validate or confirm it and reports
`AUTO_ROLLBACK_PENDING` so the confirmed-commit timer is the safety mechanism.

Successful validation opens another fresh session and confirms the pending
commit without loading configuration. Known confirmation failure is
`CONFIRMATION_FAILED`; uncertain confirmation is `CONFIRMATION_AMBIGUOUS`.
Neither is retried. Confirmation is phase-aware: failure before the RPC or a
known RPC rejection is failed, transport uncertainty during the RPC is
ambiguous, and a known successful response remains successful even if later
Config unlock or Device close reports a bounded cleanup warning. An ambiguous
commit-confirmed result is not retried, confirmed, or manually rolled back; if
it became active, the confirmation timer should restore the prior committed
configuration.

Evidence records bounded phase results and never raw NETCONF replies, full
configuration, candidate diff, or credentials. The first real Junos write still
requires separate review and explicit approval of the exact immutable digest.

## Limitations

Increment 4 supports one interface description on one explicit Junos target. It
does not provide fleets, arbitrary XML, rollback 1 automation, proxy/bastion
routing, dynamic device credentials, or a claim of generic cross-vendor
transactions. Completion remains blocked on real vJunos plan/write acceptance.
