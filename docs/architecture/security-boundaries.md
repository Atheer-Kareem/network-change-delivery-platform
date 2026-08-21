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

The mature identity chain is Buildkite OIDC to OpenBao JWT validation to a
short-lived OpenBao token to narrowly scoped device credentials. Secrets and
secret-bearing payloads never enter Git, application models, logs, artifacts, or
evidence. Company data of any kind is forbidden; only synthetic personal-lab data
may be used.

The three zones may share physical hardware in the personal lab. Containers and
services on one MacBook provide logical separation only; they are not equivalent
to production host, network, identity, or administrative isolation.
