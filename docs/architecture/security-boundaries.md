# Security boundaries

## Trust principles

Privilege follows validated artifacts, not repository presence. The exact
protected-branch commit and immutable plan digest approved by a human must be the
artifacts executed. Identity, targets, relevant state, and remaining work are
checked immediately before writes. Unsupported or stale inputs fail closed.
There is no silent credential, endpoint, or protocol fallback and no automatic
retry after an ambiguous write.

## Zone 1 — PR validation

Potentially untrusted changes run without device write credentials or network
write access. Work is limited to schema, policy, lint, unit, rendering, and
assurance checks, using only read-only source-of-truth access where required and
sanitized configuration snapshots.

## Zone 2 — deployment

Only the exact approved protected-branch commit may enter this zone with its
immutable plan identity and digest. It obtains narrowly scoped, short-lived
secrets, reaches management networks, enforces concurrency, re-verifies identity
and state, and executes only the approved artifact.

## Zone 3 — continuous operations

Monitoring, configuration history, and telemetry use read-only or minimally
privileged identities. They operate independently and never reuse ordinary
deployment write credentials.

## Credential and data boundaries

The personal-lab path uses bounded AppRole bootstrap credentials to obtain a
short-lived, single-use, exact-path OpenBao token for a static device credential.
The mature identity chain is Buildkite-issued OIDC JWT to OpenBao signature and
role validation to mapped job identity and a short-lived OpenBao token, followed
by stronger device authorization. NCDP binds OpenBao-verified pipeline, commit,
branch, step, and job metadata to its validated runtime context. The 7B-A
application boundary is implemented but is not active in Buildkite until the
external OpenBao role and pipeline integration are accepted. Secrets and
secret-bearing payloads never enter Git, application models, logs, artifacts, or
evidence. Company data of any kind is forbidden; only synthetic personal-lab data
may be used.

The three zones may share physical hardware in the personal lab. Containers and
services on one MacBook provide logical separation only; they are not equivalent
to production host, network, identity, or administrative isolation.
## Buildkite promotion boundary

Increment 7A promotion bundles bind exact commit, plan, policy, baseline, and
PASSED assurance bytes. The deployment gate performs offline verification only.
Environment variables are not Buildkite identity proof; OIDC federation is 7B.
