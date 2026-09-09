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

Disposable profiled CML integration is a separate credentialed assurance
boundary on `ncdp-staging`. The temporary ACTIVE exception schedules it only
on canonical non-PR main; retained PR hook admission is used when PR staging is
explicitly restored. Its success remains a main promotion prerequisite. An agent-owned
command hook checks the exact command,
step, queue, canonical repository/PR origin, and retry zero before sourcing its
protected environment, after repository pre-command hooks. Before sourcing it
requires an agent-owned, regular, non-symlink file with exact mode `0600`. Before
checkout wrapper execution it binds the job pipeline UUID to the existing
OpenBao pipeline subject supplied as protected `NCDP_BUILDKITE_PIPELINE_ID`.
The driver repeats that equality check before any helper or external authority
use. Missing or mismatched identity fails closed. It injects dedicated
read-only NetBox authority and the existing four device-scoped staging JWT
roles. The personal CML license requires operator authentication to mint one
process-memory bearer; this is explicitly not least-privilege CML authority.
The accepted lifecycle owns only its disposable graph and transit-ios-01
STOP/START recycle. It cannot apply device CLI configuration or touch NCDP Live.

## Zone 2 — deployment

Only the current `profiled-deploy` command may enter this zone with a
schema-v2 plan and exact approval digest. It obtains narrowly scoped,
short-lived OpenBao tokens for static device credentials, uses the explicit profiled
LIVE trust generation,
re-verifies complete identity and state, and executes only the approved
operation-specific artifact. The personal-lab Buildkite main tail may invoke
that same CLI only after same-build schema-v2 promotion, all validation and
assurance receipts, exact human-block authorization, and fresh LIVE trust.
Its agent-owned command hook releases dedicated deploy-agent AppRole/NetBox authority
only to the exact main plan/deploy steps. This is not the retired deployment JWT
role family. PRs cannot schedule the write tail. See the
[current boundary](buildkite-profiled-delivery-operations.md).

All repository commands soft-fail for presentation; the aggregate Buildkite
status is no longer a reliable merge-safety gate. Missing/invalid prerequisites
still prevent deployment, even after human unblock. Same-build receipts and
unblocker metadata trust the Buildkite scheduler, canonical reviewed main and
agent owner; they do not provide independent cryptographic proof against a
compromised administrator, trusted checkout or shared single-user host.

IOSv/IOSvL2 interface-description operation admission reuses the Cisco lifecycle,
but does not extend `ncdp-buildkite-profiled-deploy` credential permission beyond
devices 1/2. Devices 8/9 remain unavailable to that role. No fallback identity or
credential injection is authorized. See [profile reuse](profile-reuse-write.md).

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
retired. Current profiled local execution uses the personal-lab AppRole
mechanism and exact stable-device-ID KV reads. The Buildkite deploy agent uses
its own persistent SecretID (unlimited lifetime/logins) with fresh 300-second,
one-use tokens. Installed and repository exact reads are now devices 1/2/8/9
after explicitly approved and verified activation under
[rollout Increment 3](profiled-rollout-runtime-planning.md). This explicitly accepted
single-user MacBook convenience does not change delivery authorization; the
general operator AppRole retains its bounded settings.
Secrets and secret-bearing payloads never enter Git, evidence models, logs,
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
history and audit. No current command or pipeline step can execute them. Current
schema-v2 protected main delivery uses the new profiled boundary
described above, not restoration of the schema-v1 gate.

Cisco profiled execution verifies exact pinned collection manifests and the
adapter's effective Runner path before credential/device activity. This accepted
local prerequisite is not cryptographic content verification and does not apply
to Junos. See [runtime operations](buildkite-profiled-delivery-operations.md).
