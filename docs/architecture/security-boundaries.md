# Security boundaries

## Trust principles

Privilege follows validated artifacts, not repository presence. The current
local write boundary requires an immutable schema-v2 plan, its exact digest,
and explicit `--live`. Identity, targets, relevant state, and remaining work
are checked immediately before writes. Unsupported or stale inputs fail closed.
There is no silent credential, endpoint, or protocol fallback and no automatic
retry after an ambiguous write.

## Zone 1 — PR validation

Potentially untrusted changes run without device write credentials or network
write access. Work is limited to schema, policy, lint, unit, rendering, and
assurance checks, using only read-only source-of-truth access where required and
sanitized configuration snapshots.

## Zone 2 — deployment

Only the explicit local `profiled-deploy` command may enter this zone with a
schema-v2 plan and exact approval digest. It obtains narrowly scoped,
short-lived credentials, uses the explicit profiled LIVE trust generation,
re-verifies complete identity and state, and executes only the approved
operation-specific artifact. The Buildkite pipeline has no deployment zone or
device-write authority.

## Zone 3 — continuous operations

Monitoring, configuration history, and telemetry use read-only or minimally
privileged identities. They operate independently and never reuse ordinary
deployment write credentials.

Increment 11A narrows the first telemetry boundary further: Prometheus and
Blackbox receive no credential. A host-side materializer uses private read-only
NetBox and CML realization authority, then exposes only private TCP targets to
the containers. Raw endpoints never become durable metric identity, and neither
Oxidized nor generic user SSH trust is reused. Loss of authority removes probe
authorization; it never enables a fallback or deployment action.

## Credential and data boundaries

The personal-lab path uses bounded AppRole bootstrap credentials to obtain a
short-lived, single-use, exact-path OpenBao token for a static device credential.
The historical protected-delivery identity chain used Buildkite OIDC and
claim-bound OpenBao roles. It remains accepted historical evidence but is not a
current credential path: its privileged CLI and pipeline entry points are
retired. Current profiled local execution uses the bounded personal-lab AppRole
mechanism and exact stable-device-ID KV reads.
Secrets and secret-bearing payloads never enter Git, application models, logs,
artifacts, or evidence. Company data of any kind is forbidden; only synthetic
personal-lab data may be used.

The three zones may share physical hardware in the personal lab. Containers and
services on one MacBook provide logical separation only; they are not equivalent
to production host, network, identity, or administrative isolation.
## Historical Buildkite promotion boundary

Increment 7A promotion bundles bound exact commit, plan, policy, baseline, and
PASSED assurance bytes. Environment variables are not Buildkite identity proof.
The 7B gate required a Buildkite-signed JWT, OpenBao signature and role
validation, mapped identity metadata, and NCDP's exact runtime comparison before
offline promotion verification.

The accepted 7C path required a commit-bound exact-plan request and one
device-specific token. Those contracts and artifacts remain parseable for
history and audit. No current command or pipeline step can execute them. Future
protected delivery requires a new profiled design rather than restoration of
the schema-v1 gate.
