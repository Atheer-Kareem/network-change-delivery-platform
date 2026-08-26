# Immutable approval, fleet rollout, recovery, and evidence

**Status:** Accepted

**Date:** 2026-08-21

## Context

Fleet delivery spans review and execution time, multiple devices, partial
failure, vendor-specific recovery, and later operational discovery.

## Decision

Resolve and preflight the complete target set before writes. Freeze it in an
immutable plan with a canonical digest. Approval preview and machine execution
derive from that one artifact. Fresh identity, state, support, and still-required
change checks run immediately before writing; stale plans fail closed.

Deploy one canary per representative platform, then bounded waves with independent
validation. Failure stops subsequent waves. Report partial outcomes honestly and
never automatically retry an ambiguous write. Immediate recovery uses proven
vendor-aware mechanisms. Increment 9 narrows the implemented recovery baseline:
automated historical ancestry, inverse generation, and later-change conflict
handling are deferred. A later rollback is a new reviewed desired-state change
through the ordinary delivery pipeline; Git history alone does not authorize a
device write.

A future typed `ChangeRecord` correlates the PR, commit, build, container,
inventory, targets, plan and digest, approval, assurance, twin, per-device
preflight, execution, validation, rollout, outcome, configuration history, and
recovery ancestry. Monitoring remains independent of deployment completion.

## Rationale

Approval is meaningful only when it identifies exactly what runs. Fleet and
recovery state cannot be represented honestly by command success or Git history.

## Consequences

Changes may stop safely rather than deploy partially by accident. No fleet-wide
atomicity is promised. Evidence excludes credentials and must represent no-ops,
ambiguity, partial success, recovery, and validation separately.

## Deferred decisions

Canonical serialization, digest algorithm, evidence storage, approval UI,
concurrency backend, wave policy, and per-change vendor recovery mechanics.
