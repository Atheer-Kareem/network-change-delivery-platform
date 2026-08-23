# Increment 7C protected live-deployment acceptance

Status: complete, including protected-main external live-deployment acceptance.

## Accepted capability

Increment 7C accepts this personal-CML, single-device chain:

```text
protected-main commit
→ offline promotion and plan-bound assurance
→ exact human approval
→ commit-bound live request
→ exact deployment-runtime prerequisite verification
→ fresh privileged Buildkite OIDC JWT
→ device-specific least-privilege OpenBao token
→ exact one-device KV credential read
→ NetBox-authoritative inventory resolution
→ fresh IOS XE preflight
→ exact approved artifact execution
→ fresh independent post-write validation
→ typed ChangeRecord evidence
```

The accepted plan is `CHG-BUILDKITE-7C-001`, digest
`sha256:088ce8012958f3eb6fd8165d2a65b9d090d7a9a41e00386c9c914dfc29fc19eb`.
It targets `core-02`, `netbox:dcim.device:1`,
`netbox:dcim.interface:2`, and Cisco IOS XE `GigabitEthernet2`. The immutable
change moves the description from
`managed-by-network-change-delivery-platform` to
`managed-by-ncdp-buildkite-7c-001` using `cisco_targeted_inverse` through
`ansible-runner/cisco.ios`. `GigabitEthernet1` remains the protected management
interface.

Buildkite fleet deployment remains unsupported. This acceptance covers one
personal-CML device and does not claim fleet-wide atomicity.

## Accepted live result

Protected-main Buildkite build #46 ran commit
`a49a75f7224622d3abd9198e08a43fb751513b84` with these exact promotion values:

- Plan digest: `sha256:088ce8012958f3eb6fd8165d2a65b9d090d7a9a41e00386c9c914dfc29fc19eb`
- Assurance digest: `sha256:da9f8602c52a2e4764d4e7bec871b6b6dd3c7147d01234f9b2ea703e07a8ae3b`
- Promotion digest: `sha256:59f34c5dc133d2332047c591d74be1f171c3ecc063d3446b4585f5ecb203f1f7`

The deployment runtime verified `ansible.netcommon=8.6.0` and
`cisco.ios=11.4.2`. The successful version 1 `ChangeRecord` recorded:

```text
change_id = CHG-BUILDKITE-7C-001
plan_digest = sha256:088ce8012958f3eb6fd8165d2a65b9d090d7a9a41e00386c9c914dfc29fc19eb

preflight.attempted = true
preflight.succeeded = true
preflight.observed_description = managed-by-network-change-delivery-platform
preflight.message = fresh identity and interface preconditions verified

execution.attempted = true
execution.succeeded = true
execution.changed = false
execution.message = exact approved configuration artifact completed successfully

post_validation.attempted = true
post_validation.succeeded = true
post_validation.observed_description = managed-by-ncdp-buildkite-7c-001
post_validation.message = fresh observed description matches desired state

recovery.attempted = false
final_outcome = SUCCEEDED
provider = ansible-runner/cisco.ios
```

`execution.changed = false` is retained exactly as provider-reported historical
evidence. NCDP's authoritative success condition was the successful execution
disposition followed by fresh independent post-write collection matching the
desired state. The independent pre/post observations prove the intended state
transition without rewriting the provider field.

## Independent verification

A separate read-only acceptance pass resolved `core-02` through NetBox as
`netbox:dcim.device:1`, with `GigabitEthernet2` identified as
`netbox:dcim.interface:2`, host `192.168.4.14`, and platform `cisco_iosxe`.
It then independently collected live device state and verified:

- hostname remained `core-02`;
- `GigabitEthernet2` existed, was not protected, and had description
  `managed-by-ncdp-buildkite-7c-001`;
- `GigabitEthernet1` existed, had no description, remained protected, and did
  not receive the GigabitEthernet2 description; and
- no recovery was required.

The independent verification was read-only and executed no configuration
command.

## Failure-driven hardening progression

The first external attempt blocked during preflight before execution and wrote
nothing. That result led to fixed, sanitized boundary-level attribution in typed
evidence without exposing provider errors or secret material.

Retry #2 passed inventory and credential-reference resolution, privileged
OpenBao JWT authentication and policy validation, and the exact KV credential
read. It then reported `device state collection blocked`, with execution not
attempted and zero device writes. Read-only diagnosis proved that the deployment
runtime lacked the exact repository pins `ansible.netcommon` 8.6.0 and
`cisco.ios` 11.4.2. The durable control verifies pinned collection metadata
offline before requesting the privileged deployment JWT. The persistent agent
runtime was provisioned at
`/Users/netdevops/.local/share/ncdp/ansible/collections` with those direct pins
and required transitive dependency `ansible.utils` 6.1.0, and the repository
verifier passed before and after the deployment-agent restart. Provisioning
performed no device write.

On build #46 the runtime guard passed, but the first deployment-gate job was
interrupted by the local macOS Local Network permission boundary during device
state collection. Its typed evidence remained `BLOCKED`, execution was not
attempted, and no write occurred. After the operator granted that host
permission, retrying the failed `deploy-gate` within the same already-approved
build created another deployment-job attempt and produced the accepted
successful result.

That success exposed that an already-human-approved build could obtain another
deployment-job attempt through Buildkite retry. The durable single-attempt
control now disables automatic and manual retry on `deploy-gate` and rejects
every `BUILDKITE_RETRY_COUNT != 0` or malformed value before commit verification
or either OIDC request. The hardened control prohibits a second `deploy-gate`
attempt within the same human-approved Buildkite build. Another attempt requires
a new Buildkite build and fresh human approval. NCDP operating procedure also
requires an explicit fresh commit-bound retry marker for intentional retries;
Increment 7C does not claim to disable Buildkite's separate pipeline-level
full-build Rebuild capability.

The hardening merged as commit
`577cad91da18d146ac27763e28de5e25585fae6c`. Protected-main build #48 succeeded
with the unchanged request and therefore stopped in the no-request/no-write
path:

```text
plan digest: sha256:088ce8012958f3eb6fd8165d2a65b9d090d7a9a41e00386c9c914dfc29fc19eb
assurance digest: sha256:6c9fdf53b084617a1c26cba438240df366ef29c6bbb751b51439b500db721345
promotion digest: sha256:5c2300ad40a8c05b604f884b47693b5e9b2b1bef41e3cb0240539a387065889d
deployment authorization gate: PASSED
live deployment requested: NO
device write executed: NO
```

Build #48 terminated before privileged credentials or device access. A retried
#48 job was intentionally not exercised. Replay prevention is accepted through
the Buildkite schema and pipeline contract, repository dynamic tests, the merged
protected-main pipeline, and the successful external no-request/no-write build.

## Security acceptance

- Exact commit-bound request: **YES**.
- Immutable plan digest binding: **YES**.
- Human approval: **YES**.
- Buildkite workload identity: **YES**.
- Privileged OIDC token short-lived: **YES**.
- Device-specific OpenBao role: **YES**.
- Exact one-device KV read capability: **YES**.
- No default policy: **YES**.
- NetBox inventory read-only: **YES**.
- Pinned Ansible runtime verified before privileged deployment JWT: **YES**.
- SSH host trust required: **YES**.
- Management interface protected: **YES**.
- Execution independently post-validated: **YES**.
- Typed evidence uploaded: **YES**.
- Failed preflight produced zero device write: **YES**.
- Retried deployment gate prohibited after hardening: **YES**.
- One approved build permits at most one deployment-job attempt: **YES**.
- Secret material absent from repository, logs, and evidence: **YES**.

## Scope boundaries and non-claims

- Buildkite fleet deployment remains unsupported.
- Pipeline-level full-build Rebuild prohibition is not claimed. A rebuilt build
  is a distinct Buildkite authorization context and still requires fresh human
  approval.
- No fleet-wide atomicity is claimed.
- Personal-lab host isolation is not production infrastructure.
- Terraform/CML lifecycle remains Increment 8.
- Delayed rollback remains Increment 9.
- Durable audit chronology remains Increment 10.
- Continuous observability remains Increment 11.
