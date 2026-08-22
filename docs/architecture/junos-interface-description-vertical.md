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

## Validation, confirmation, and honest outcomes

Known commit-confirmed success closes the transaction session. Independent
post-validation opens a fresh PyEZ/NETCONF session and verifies hostname,
interface identity/existence, and exact desired description. A failure is
`AUTO_ROLLBACK_PENDING`: NCDP sends no confirmation or other write and does not
claim recovery before later independent observation.

Successful validation opens another fresh session and confirms the pending
commit without loading configuration. Known confirmation failure is
`CONFIRMATION_FAILED`; uncertain confirmation is `CONFIRMATION_AMBIGUOUS`.
Neither is retried. An ambiguous commit-confirmed result is not retried,
confirmed, or manually rolled back; if it became active, the confirmation timer
should restore the prior committed configuration.

Evidence records bounded phase results and never raw NETCONF replies, full
configuration, candidate diff, or credentials. The first real Junos write still
requires separate review and explicit approval of the exact immutable digest.

## Limitations

Increment 4 supports one interface description on one explicit Junos target. It
does not provide fleets, arbitrary XML, rollback 1 automation, proxy/bastion
routing, dynamic device credentials, or a claim of generic cross-vendor
transactions. Completion remains blocked on real vJunos plan/write acceptance.
