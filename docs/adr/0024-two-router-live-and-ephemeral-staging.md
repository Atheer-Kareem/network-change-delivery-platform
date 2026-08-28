# ADR 0024: Two-router live and ephemeral staging

- Status: Accepted
- Date: 2026-08-29

The number 0023 is intentionally not reused. Historical ADR 0023 was accepted,
later reverted by the explicit PR #66 baseline rollback, and remains available
in Git history only.

## Context

The personal lab needs one continuously available live environment and one
disposable staging environment without duplicating logical inventory or
credential identities.

## Decision

The only managed routers are NetBox device 1, `core-02`, and device 2,
`edge-junos-01`. Their live primary management addresses remain
`192.168.4.14/24` and `192.168.4.20/24`. NetBox also assigns staging secondary
addresses `192.168.4.30/24` and `192.168.4.40/24` to those same devices and
management interfaces.

Each logical device has one OpenBao credential at `ncdp/devices/<id>/ssh`.
Live and staging realizations intentionally reuse that device credential;
credentials belong to logical device identity rather than a management IP.

The manually owned persistent CML lab is `NCDP Live`. It remains outside
Terraform ownership, normally stays running, and contains management
infrastructure plus the direct topology `core-02 ↔ edge-junos-01`.

Terraform creates a separate `NCDP Staging <run-id>` lab with the same logical
two-router topology, the secondary management addresses, and a run-scoped local
state. Staging creates, starts, validates, destroys, and independently proves
the disposable realization absent. Terraform never imports, adopts, changes,
or destroys `NCDP Live`.

## Consequences

Live and staging can run concurrently because their management addresses are
distinct. NetBox remains a two-device authority with four assigned management
IPs, while OpenBao remains a two-secret authority. Terraform state and cleanup
authority apply only to the disposable staging lab.
