# Current profiled Buildkite delivery operations

This personal-lab boundary wraps the current schema-v2 CLI, not historical
schema-v1 protected delivery. The user-supplied [current
acceptance](../acceptance/profiled-main-delivery.md)
records positive and negative main outcomes. Main planning
is read-only; execution requires same-build promotion and explicit human unblock.
Never run a live plan or deploy as an implementation/unit-test gate.

## Deployment runtime prerequisite — CAP-RUNTIME-VERIFY

Current `ncdp profiled-deploy` calls `execute_profiled_plan`. After exact plan
and approval-digest checks, Ansible-backed operation admission verifies the
selected Cisco adapter's runtime before inventory preflight, credential loading,
device collection or writer invocation. The adapter reuses
`verify_deployment_ansible_runtime` with its own repository root and the same
effective collection-path resolver used by Runner. Junos skips this prerequisite.

The existing pins remain `ansible.netcommon == 8.6.0` and
`cisco.ios == 11.4.2`. Missing, wrong, malformed, duplicate or ambiguous collection
metadata and invalid search paths produce a bounded `BLOCKED` record: preflight
failed, execution/post-validation/recovery not attempted. No installation, retry,
credential change or speculative write occurs. This verifies manifest/version
and path consistency, not collection-file cryptographic integrity.

Buildkite retains its single invocation of the same CLI after independently
checking promotion/authorization; there is no Buildkite-only runtime verifier.
See the [capability ledger](../roadmap.md#cap-runtime-verify--verified-profiled-deployment-runtime)
for explicit user acceptance after merged #140 and `tests/test_profiled_runtime_admission.py` for
offline call-path evidence.

## Agent-owned prerequisite

Use the existing `ncdp-deploy` queue. Install reviewed source
`scripts/buildkite/profiled_deploy_agent_command_hook.sh` as:

```text
/Users/netdevops/.config/buildkite/ncdp-lab/hooks/ncdp-deploy/command
```

The directory and command are agent-owned mode `0700`; adjacent `profiled.env`
is regular, non-symlink, agent-owned, exact mode `0600`. Configure the agent's
`hooks-path` to that directory. The agent launcher must NOT export NetBox,
AppRole, device or CML credentials into the agent environment. Repository
pre-command hooks must finish before protected authority is sourced by this
command hook. Do not use an environment/pre-command hook for credential release.

The command hook admits only canonical repository, non-PR main, retry zero,
queue `ncdp-deploy`, exact command `.buildkite/scripts/profiled_delivery.sh`,
and step `profiled-live-plan` or `profiled-deploy`. It checks full commit/HEAD
equality and clean tracked/untracked checkout before sourcing; immediately
after sourcing it requires the protected expected pipeline UUID. The driver
repeats context/pipeline binding and uses existing `verify_commit.sh`, including
current `origin/main`, before any provider use. Older queued-main plans can
therefore fail closed if main has advanced. Never bypass this to reuse a plan.

Required protected names:

- `NCDP_BUILDKITE_PIPELINE_ID` — the existing staging-bound pipeline UUID
- `NCDP_PROFILED_DELIVERY_STATE_ROOT` — absolute, outside checkout, agent-owned,
  non-symlink directory mode `0700`
- `NCDP_NETBOX_URL`, `NCDP_NETBOX_TOKEN`
- `NCDP_OPENBAO_URL`, `NCDP_OPENBAO_ROLE_ID`, `NCDP_OPENBAO_SECRET_ID`

The NetBox settings remain in the existing private external environment.
The deploy agent uses its own persistent AppRole, not the operator's
`ncdp-personal-lab` pair. Credential values never enter Git, arguments, logs,
plans or evidence. The personal-Mac credential is deliberately long-lived for
reliable demonstrations, not production identity isolation.

### One-time persistent deploy-agent installation

Dedicated AppRole: `ncdp-buildkite-profiled-deploy`.
Dedicated policy: `ncdp-buildkite-profiled-deploy-read`, permitting only GET reads
of `ncdp/data/devices/1/ssh` and `ncdp/data/devices/2/ssh`. It grants no
OpenBao administration, list/wildcard, secret-write or devices 8/9 access.

The role requires a SecretID with TTL **0 (non-expiring)** and use limit
**0 (unlimited)**. Every login issues a **300-second, one-use service token**
with no default policy. The token is consumed by one exact KV-v2 read; NCDP
does not cache/renew it. Plan and deploy independently log in. There is no
30-minute build-wide credential countdown.

From a reviewed operator checkout, with `BAO_TOKEN` and `NCDP_OPENBAO_URL`
already supplied securely:

```sh
uv run --frozen python scripts/buildkite/install_profiled_deploy_identity.py
```

This operator-only helper rejects Buildkite execution. It creates/updates only
the dedicated policy/role, verifies read-back, and installs its private pair at:

```text
/Users/netdevops/.local/state/ncdp/openbao/buildkite-profiled-deploy/approle.env
```

The directory is agent-owned `0700`; the pair file is `0600`. The installer
atomically updates `profiled.env` to source that file instead of reading the
shared `openbao/operator/approle-role-id` and `approle-secret-id` files.
NetBox settings, state root and pipeline binding are preserved. The trusted
command hook is unchanged and reads the dedicated pair only after its existing
admission checks; no agent restart is required. A process already running
retains its own environment.

Rerunning the installer reuses and verifies the existing dedicated pair instead
of minting another SecretID. It verifies persistent SecretID metadata, token
TTL/use/effective policy through an operator token lookup, and actual
`OpenBaoSecretProvider` credential reads for devices 1/2 without printing them.
It does not contact devices, NetBox or CML, or change any device credential.
There is no routine preparation/retirement command or automatic rotation.
The previous bounded-session helper was removed.

An `issuance-pending` marker prevents blind reissuance after an uncertain
first issuance or failed credential publication. Retain that private state for
operator review if installation fails. A saved pair is reused if only the
`profiled.env` update failed. Do not delete a valid pair merely to rerun setup.
The existing general `ncdp-personal-lab` role remains 30-minute / 10-use and is
not modified or consumed by this agent.

Before a demonstration, ensure local services are available and validate the
existing profiled LIVE trust under
`/Users/netdevops/.config/ncdp/profiled-live/ssh`; do not regenerate it or query
devices merely for installation. After merging the reviewed source, start a
fresh non-PR `main` build. Do not retry an old failed plan/deploy job or reuse
its retained state. No special demo flag or credential-preparation window is
needed. Review the immutable promotion before human unblock.

This preserves all application authorization: validation/assurance receipts,
schema-v2 plan/promotion, exact main/commit identity, human approval and fresh
deployment preflight. A stolen persistent local credential remains usable until
revoked; that is an explicit single-user MacBook lab tradeoff. OpenBao
availability/unseal, revoked credentials, stale plans, device availability and
host-trust changes can still fail a run. A persistent SecretID is not a promise
that every demonstration can write; already-compliant targets remain no-change.

## State, artifacts and authorization

Plan/deploy state is create-only under `<state-root>/<build-uuid>/<step-key>/`.
Files are private `0600`, directories `0700`, and retained after any outcome;
an existing step directory cannot be reused. This is separate from disposable
CML state. Concurrent individual plan/deploy commands are serialized by
`ncdp/profiled-live-delivery`; the human pause does not hold a fleet-wide lock.
Another build can change state during approval, so fresh CLI stale-plan/state
checks remain essential. No mutation replay is permitted.

Exact artifact names are `profiled-<build-uuid>-plan.json`,
`profiled-<build-uuid>-promotion.json`, and `profiled-<build-uuid>-record.json`.
Downloads explicitly select the same build UUID and exact producer step, into
new private directories. Promotion validates the schema-v2 plan, fixed reviewed
device-1 intent, all 13 build/commit/step success receipts and both verified
assurance digests. It binds the byte-level plan hash as well as the plan's own
digest. The immutable manifest self-digest is also published in same-build
metadata. Failed/no-change planning cannot mint a promotion.

The fieldless block immediately follows promotion. Its annotation exposes the
exact plan and promotion digests; unblock is authorization of this build and
promotion only. Deployment checks the exact committed single-block DAG,
Buildkite's canonical unblocker UUID, promotion/plan/receipt equality and LIVE
trust before invoking `ncdp profiled-deploy` once with the exact plan digest.
The [unblocker variable](https://buildkite.com/docs/pipelines/configure/environment-variables)
is scheduler supplied, not a user-entered digest field.
Missing authority produces a concise NO WRITE failure, not a substitute plan.
Human unblock cannot override missing/failed prerequisites.

Buildkite metadata and unblocker identity are trusted scheduler provenance in
this single-user lab, not cryptographically signed independent authorization.
Protect Buildkite administration, reviewed main and agent-owned files. Do not
claim isolation from a malicious administrator or compromised trusted main.

The fixed intent uses the already accepted PR #132 target, device 1/core-02,
interface 2/GigabitEthernet2, with description `managed-by-ncdp-profiled-demo`.
The existing CLI still admits only interface-description writes on profiles
1/2; this wrapper narrows to one device-1 target. Devices 8/9, B4 D1, fleet and
SNMP writes are not enabled. Already compliant means no plan and no write; do
not reset device state to manufacture a demonstration.

## Evidence and failures

Applications retain real exit codes. Buildkite soft-fails commands and schedules
later steps; it does not grant write authority. The final step validates any
available schema-v2 execution record against the exact executed plan and shows
actual execution/recovery attempts. All duplicated approved bindings are verified
before publication and final rendering, not just digest equality.
No record is fabricated. Missing publication is not evidence of no write: inspect
the retained private report before any new attempt. Primary execution failure
is preserved if annotation/artifact publication also fails. A successful command
without valid published typed evidence fails the wrapper.

Plan annotations contain bounded identity, interface, current/desired description,
strategy, plan digest and change-required facts. Provider stdout/stderr is
captured, never dumped. Artifacts contain typed plans/manifests/records, not
credentials, JWTs, Terraform state or raw device configuration. Current schema-v2
artifacts do not yet enter the historical durable
AuditStore/PRE-write-POST/viewer chain. That machinery remains available;
CAP-DURABLE-EVIDENCE and CAP-CONFIG-CHRONOLOGY own reconnection. The accepted
record reports `execution.changed == false` despite observed state transition;
that historical provider metadata is not observational change truth. Newly
normalized missing/censored/non-boolean provider metadata is unknown (`null`),
and independent `post_validation.changed` records comparable observed transition.
See [stage semantics](change-lifecycle.md#provider-metadata-observation-and-outcome).

Successful compliant planning publishes a schema-v2 `ProfiledComplianceRecord`
with its own canonical digest, exact identities/state and false authority/attempt
flags. The `profiled-planning-result` receipt binds build UUID, source commit,
artifact kind, exact bytes and result digest. Each downstream step retrieves that
exact artifact from `profiled-live-plan` in the same build and validates it.
No artifact-absence fallback is allowed. Promotion mints nothing; deploy returns
COMPLIANT without invoking the CLI or device providers; final evidence renders
write attempted false, recovery attempted false and promotion minted false.
The static human block may still appear. Continuing it creates no authority.
This describes the planning observation, not a new live acceptance or proof that
other assurance steps succeeded. Invalid/missing receipts or artifacts remain
failures; neither a missing plan nor failed planning is compliant. The CLI's
optional `--compliance-output` exposes the same artifact without another planner.

Failed planning emits only a closed phase: `commit/context`, `protected
environment`, `LIVE trust`, `NetBox inventory`, `OpenBao login`, `OpenBao credential read`, `device
read-only preflight`, or `plan publication`. AppRole login/issued-token failures
map to OpenBao login; KV access/path/payload failures map to OpenBao credential
read. Provider and exception bodies are never printed.
Annotation publication failure does not replace the primary nonzero plan result.

Bootstrap remains `buildkite-agent pipeline upload .buildkite/pipeline.yml`.
The retired demo renderer/path-filter bootstrap is not current architecture.
PR execution cannot validate the main write tail. The supplied main acceptance
is linked above; any new run still needs separate authorization and human unblock.
No static pipeline scheduling, retry policy or main assurance prerequisite is
changed by the outcome refinement. The PR CML exception remains ACTIVE.
