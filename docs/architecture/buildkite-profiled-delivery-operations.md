# Current profiled Buildkite delivery operations

This personal-lab boundary wraps the current schema-v2 CLI, not historical
schema-v1 protected delivery. Runtime acceptance remains PENDING. Main planning
is read-only; execution requires same-build promotion and explicit human unblock.
Never run a live plan or deploy as an implementation/unit-test gate.

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

The existing operator-owned NetBox environment and private AppRole source files
may be referenced only inside this protected environment. Never copy values into
Git, command arguments, logs or test fixtures. No new OpenBao roles, secret
values or AppRole configuration are installed. This operator bootstrap is not
least-privilege production deployment identity or the retired JWT role family.
Validate the existing profiled LIVE trust under
`/Users/netdevops/.config/ncdp/profiled-live/ssh`; do not generate trust on demand,
use ambient SSH trust, or collect devices merely to check installation.

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
available schema-v2 execution record and shows actual execution/recovery attempts.
No record is fabricated. Missing publication is not evidence of no write: inspect
the retained private report before any new attempt. Primary execution failure
is preserved if annotation/artifact publication also fails. A successful command
without valid published typed evidence fails the wrapper.

Plan annotations contain bounded identity, interface, current/desired description,
strategy, plan digest and change-required facts. Provider stdout/stderr is
captured, never dumped. Artifacts contain typed plans/manifests/records, not
credentials, JWTs, Terraform state or raw device configuration. Historical
AuditStore acceptance is not replaced or fabricated by this new artifact path.

Bootstrap remains `buildkite-agent pipeline upload .buildkite/pipeline.yml`.
If an external bootstrap still invokes the retired demo renderer, its operator
must restore ordinary upload after this source merges. No live pipeline settings
change is part of implementation. PR execution cannot validate the main write
tail; that requires a later explicitly authorized main run and human unblock.
