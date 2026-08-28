# Buildkite ephemeral CML staging operations

## Active simplified model

Pull requests and non-main builds run quality and contract validation only.
After the separate cutover, a reviewed merged-main build may run the
credentialed disposable lifecycle on the existing `ncdp-staging` agent under
`netdevops`. The wrapper invokes `ncdp-staging-controller`, which requires
branch `main`, no pull request, exact step/queue/retry identity, devices 6/7,
OpenBao roles/references 6/7, the ten-resource graph, and the brownfield/live
denial boundaries. Protected delivery remains independently frozen.

Checkout-independent schema-4 installation, dedicated Unix identity, protected
toolchain, token supervisor, LaunchDaemon migration, and related native/runtime
admission below are retained as deferred production-hardening reference. They
are not active lab execution prerequisites.

## Trusted agent boundary

The `cml-staging` step runs on a dedicated self-hosted `ncdp-staging` queue with
concurrency one in `ncdp/cml-ephemeral-staging`. Automatic and manual retries
are disabled. A retry is also rejected before identity or CML access. The
immutable Buildkite build UUID derives `bk-${BUILDKITE_BUILD_ID}`; build number
is not an identity.

The staging agent must install a copy of
`scripts/buildkite/staging_agent_command_hook.sh` from reviewed `main` as an
agent-owned command hook outside all checkouts. It admits only the exact staging
step, queue, and repository command and rejects a pull request whose source
repository differs from the canonical pipeline repository. This external hook
is essential: pipeline OIDC identity does not make PR-controlled code trusted.
Fork PRs retain unprivileged quality coverage but cannot use staging credentials.

An agent-owned `staging.env` file supplies, outside pipeline YAML:

- `NCDP_STAGING_STATE_ROOT`: persistent, agent-owned, absolute, non-symlink,
  outside the checkout, and mode `0700` or stricter;
- `NCDP_NETBOX_URL` and dedicated read-only `NCDP_STAGING_NETBOX_TOKEN`;
- `NCDP_OPENBAO_URL`;
- `CML2_ADDRESS`, PEM `CML2_CACERT`, and dedicated
  `NCDP_CML_STAGING_USERNAME` / `NCDP_CML_STAGING_PASSWORD`.

Ambient AppRole, `NCDP_NETBOX_TOKEN`, `CML2_TOKEN`, and direct device
credentials are rejected. State lives at
`<state-root>/ephemeral/<run-id>/`, survives job failure, and is never an
artifact. The filesystem should be encrypted because Terraform state contains
ADR 0013 Day-0 credential copies.

The credential file is deliberately not an `environment` hook. The trusted
agent `command` hook first validates the queue, exact command, and PR origin;
only then, after repository pre-command hooks have finished, does it source the
protected file and execute the exact wrapper. Checkout-controlled hooks never
receive staging credentials before admission.

## Workload identities

The operational description below is historical runtime behavior from before
the simplified devices 6/7 consumer. Phase B2 retired the staging roles and
policies for live devices 1/2 and established standing credentials, policies,
and roles for staging devices 6/7. The checked-in runtime still requests the old
roles, so `cml-staging` is intentionally unauthorized and must not run. Before
any B3 source or Terraform commit is pushed, a reviewed Buildkite execution
guard or freeze must prevent this legacy path during the half-migrated window.

Phase B2-G establishes that guard. The user LaunchAgent
`com.buildkite.ncdp-staging` is persistently disabled and unloaded, while the
pipeline independently applies explicit false conditions to `cml-staging` and
the protected-delivery group. The agent-owned hook and protected environments
remain installed for a separately reviewed B4 cutover. Neither freeze may be
removed, and the agent may not be re-enabled, before that cutover authorizes the
migrated devices 6/7 consumer.

Phase B3-1 statically changes the target ephemeral Terraform graph to the
ten-resource `modules/managed-pair` structure: System Bridge, management switch,
Cisco, Junos, four links, and one lifecycle. It deliberately does not change
the historical devices 1/2 authority selection or restore runtime execution.
The external and pipeline freezes therefore remain mandatory for B3-2.

Phase B3-2A implements the future controller as installation source without
installing or activating it. Privileged execution will use an agent-owned,
digest-verified bundle outside the checkout and an external immutable manifest
binding devices 6/7, homologs 1/2, `.30/.31`, exact staging OpenBao authority,
the CML connector/images, the brownfield-lab denial, and the ten-resource graph.
The controller never executes checkout Python or Terraform with protected
authority. It owns the run state path and applies only the exact saved plan that
passed trusted structural parsing. B3-2B owns installation from exact clean
merged main; B4 owns the later hook cutover and re-enable.

Phase B3-2B1 completes the non-live executable composition and splits external
admission into B3-2B2. B3-2B2B0-R corrects standing ownership: the controller
binds pipeline and commit to manifest schema 4, separately validates the
root-owned reviewed source and final executable-runtime
inventories, constructs a non-inherited privileged environment, applies only exact
saved plans, supports exact-subset cleanup/recovery, and emits allowlisted
evidence. No standing runtime or command hook is changed by B3-2B1.

The service root itself remains root-owned `0750`; only named mutable children
are staging-owned `0700`. Standing construction derives its native build
environment from the admitted SDK and protected libssh roots, uses a reviewed
root-controlled uv cache, and verifies native plus Ansible authority both before
manifest finalization and again at controller startup.

Standing construction never elevates the active checkout. B3-2B2B1 must first
obtain the canonical repository's exact accepted commit into the root-owned
`/private/var/db/ncdp-staging/bootstrap/source/<commit>` class, verify it with
sanitized `/usr/bin/git`, construct a root-owned installer runtime, and only then
invoke `ncdp-protected-staging-install`. Repository Python under UID 501 is
review input, not privileged execution authority.

Native admission is transitive. One scope-qualified graph covers the runtime,
Python, libssh/OpenSSL trees, OpenSSL executable, Terraform, Buildkite Agent,
and installation-time uv. Each dependency of each protected dylib is itself
admitted; the combined graph digest rejects a protected libssh or OpenSSL object
that delegates loading to Homebrew, user, checkout, temporary, unresolved
loader-relative, or other unbound authority.

Runtime construction copies every packaging-required local asset, installs the
non-editable wheel with uv bytecode compilation enabled, inventories the final
bytecode-bearing runtime, then starts the real controller and requires the
second inventory to be identical. The manifest also binds the exact base Python
interpreter path and digest used by the virtual environment.

Before installing anything, B3-2B2 must prove the validation, staging, and
deployment OS principals and protected-root ownership/ACLs. A shared Unix UID
between checkout-controlled validation and protected staging is a hard stop;
private paths under one UID are not an isolation boundary.

Remediation must rotate every exposed cluster-registration token and bootstrap
each affected agent from a root-only descriptor. Connecting the replacement
staging agent for admission requires the exact queue to be administratively
paused; the repository freeze alone is not dispatch authority. Agent UUID
stability is measured before selecting an additional OpenBao claim. Before B4,
agent-local hooks, plugins and command evaluation are disabled and a root-owned
hook may invoke only the installed controller; cryptographic evidence
attestation remains a separate gate.

The protected OIDC request is fixed to audience
`urn:ncdp:openbao:staging`, lifetime 300 seconds, `pipeline_id` as the subject
claim, and explicit `build_id`. No caller can select these values. Protected CML
discovery follows the proven 2.10 API: the lab collection returns UUID strings,
and each exact lab detail is read separately for identity/title validation.

Historically, the job requests one five-minute Buildkite JWT with audience
`urn:ncdp:openbao:staging`, immutable pipeline UUID in `sub`, and explicit
`build_id`. The application validates pipeline, build, commit, branch, step,
job, queue, and retry context. It uses the JWT only in memory for two logins:

- `ncdp-buildkite-staging-device-1` receives only
  `ncdp-buildkite-staging-device-1-read`;
- `ncdp-buildkite-staging-device-2` receives only
  `ncdp-buildkite-staging-device-2-read`.

Each policy reads only `ncdp/data/devices/<id>/ssh`. Tokens are one-use, have no
default policy, and expire within 300 seconds. Configure and read back this
repository-owned state from a trusted shell using environment-only `BAO_TOKEN`:

```shell
uv run python scripts/openbao/configure_buildkite_staging.py
```

The tool verifies the existing NCDP-owned `jwt/` mount and backend and never
alters deployment roles. NetBox uses a distinct token limited to device,
interface, tag, and protection-metadata reads. CML 2.10 exposes lab ownership
and sharing, but the personal license rejects creation of additional users. This
environment therefore cannot supply the preferred regular staging account and
uses the existing personal-controller operator login to mint one in-memory
bearer per run. This is an explicit platform limitation, not a claim of narrow
CML authorization. The driver rejects ambient `CML2_TOKEN`; controller settings
remain outside staging.

The current standing Phase B2 OpenBao objects instead use roles
`ncdp-buildkite-staging-device-6` and `-7`, each carrying only its corresponding
exact staging-device policy. B3/B4 will update protected consumption; B2 does
not claim that migration has occurred.

## Execution and evidence

The frozen pipeline command calls
`scripts/buildkite/ephemeral_staging.sh`. The wrapper
verifies merged-main job/checkout identity, pipes the JWT to the simplified
controller, and
uploads only `staging-evidence/staging-run.json`. The authoritative state machine
remains `network_change_delivery.ephemeral_staging.run_staging_lifecycle`.

Each realization gets a run-scoped `known_hosts` file for exact
`192.168.4.30` and `192.168.4.31` trust. SSH and NETCONF remain strict; no human
trust file or earlier-build key is used. Staging performs read-only NCDP
planning/validation and never invokes `ncdp deploy`.

Evidence contains only job binding, disposable CML IDs, stable NetBox identity,
credential references, timings, and outcomes. Tokens, credentials, Day-0,
device configuration, provider bodies, and state are excluded. The wrapper
preserves the staging status when artifact upload succeeds; upload failure also
fails the job.

After B4, the agent-owned command hook will validate the exact step, queue,
command, and canonical repository, then invoke the installed protected
controller without sourcing protected authority into the checkout. Normal
controller invocation accepts only the bounded `run` operation, not target,
credential, lab, Terraform-root, address, or state-path overrides.

## Retained-state recovery

Destroy or absence failure retains the run directory. Do not retry the job,
delete CML objects manually, or manipulate state. From a trusted operator shell
with local AppRole and the exact retained run, execute:

```shell
uv run python scripts/recover_ephemeral_cml_staging.py \
  --run-id <bk-build-uuid> \
  --run-directory <state-root>/ephemeral/<bk-build-uuid> \
  --evidence <protected-recovery-evidence.json>
```

Recovery refuses empty, unknown, foreign, or extra state; reconstructs inputs;
plans only deletion of the retained managed subset; destroys; independently
proves the title and recorded CML UUIDs absent; requires empty state; and only
then retires the directory. It cannot create or start staging infrastructure.
