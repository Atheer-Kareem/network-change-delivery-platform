# ADR 0008: Exact plan-bound Batfish assurance

## Status

Accepted for Increment 6B.

## Decision

The generic Increment 6A `assure` command remains unbound diagnostic assurance.
The new `assure-plan` path accepts only a validated, digest-verified
`DeploymentPlan` or `FleetDeploymentPlan`; it never accepts a caller-supplied
candidate snapshot. Python derives the candidate deterministically from frozen
baseline bytes and the exact interface-description plan.

The reviewed behavior policy has its own canonical SHA-256 digest. A
`PlanAssuranceRecord` binds the plan subject, policy, baseline manifest,
derived-candidate manifest, bounded mutation metadata, inner Batfish evidence,
outcome, and its own content digest. `verify-assurance` re-derives the candidate
and checks all bindings without contacting Batfish.

Only the current interface-description plan and the two supported synthetic
configuration grammars are materialized. Unsupported or ambiguous input
blocks fail closed. Baseline freshness, provenance, signatures, protected
branch state, Buildkite approval, and device state at deployment time remain
outside 6B. `deploy` and `fleet-deploy` do not enforce assurance until
Increment 7.

## Consequences

6B proves content binding and offline re-verification, not authenticity or
freshness. Increment 6 is complete after review/merge; Increment 7 owns the
deployment workflow prerequisite and provenance boundary.
