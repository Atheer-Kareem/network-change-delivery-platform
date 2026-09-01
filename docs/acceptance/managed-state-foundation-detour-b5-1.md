# Detour B5-1 managed-state foundation acceptance

Date: 2026-09-01

B5-1 adds repository-only canonical managed-state and durable acceptance
contracts for `routed_underlay`, `ospf`, `vlan`, and `acl`.

The accepted implementation proves:

- observation and desired projections compare only fields in their exact
  `ManagedOwnershipEnvelope`;
- owned changes alter the canonical digest while admitted unowned diagnostic
  changes do not;
- the four canonical Git D1 digests are those recorded in
  [managed state and drift](../architecture/managed-state-drift.md);
- `ManagedStateAcceptanceEvidence` derives the existing v1
  `AcceptedManagedStateRef` without changing its schema;
- private content-addressed records form a bounded append-only, no-gap,
  no-fork chain per vertical;
- only `INITIAL_ADOPTION` and `POST_WRITE_VALIDATED` exist;
- `POST_WRITE_VALIDATED` is structurally valid only with an intrinsic,
  subject-bound `CONVERGED` O'/D1 comparison whose two digests equal the newly
  accepted canonical state; without convergence there is no D0 advancement;
- current D0 resolution validates the complete chain and never selects by
  filename order or mtime;
- D0/O, D0/D1, and O'/D1 comparisons use distinct outcome vocabularies, retain
  the exact ownership envelope, and report zero device writes.

The established B4 service and candidate digests remain unchanged. B5-1 did
not observe LIVE devices, initialize a real managed-state store, persist a real
D0, or mutate NetBox, OpenBao, CML, Terraform, credentials, trust, devices, or
pipeline authority. Initial LIVE adoption remains B5-2 work.
