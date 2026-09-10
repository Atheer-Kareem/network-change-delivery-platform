# Buildkite profiled ephemeral CML staging operations

The current assurance step reuses the profiled lifecycle locally accepted in
PR #134 and refined in #136. The user-supplied [main-delivery
acceptance](../acceptance/profiled-main-delivery.md)
records success through the current required CML prerequisite. Runtime-relevant
PR/development staging now runs under the restored [ledger
boundary](../roadmap.md#temporary-development-workflow-exceptions);
canonical non-PR main retains real staging success evidence. Schema-v1 protected
delivery remains retired; the separate current
schema-v2 main delivery tail is described in [workflow](buildkite-workflow.md).
Staging commands now soft-fail for presentation while retaining truthful exit
codes; their failure no longer necessarily blocks merge via aggregate status.

## Trusted agent boundary

The single `cml-staging` job runs on `ncdp-staging`, concurrency one in
`ncdp/cml-ephemeral-staging`. Automatic and manual retries are disabled. The
driver rejects retries and derives `bk-${BUILDKITE_BUILD_ID}` from the immutable
build UUID. Build number is not identity.

Install the reviewed
`scripts/buildkite/staging_agent_command_hook.sh` as the agent-owned
`command` hook outside all checkouts. For this personal host the target is:

```text
/Users/netdevops/.config/buildkite/ncdp-lab/hooks/ncdp-staging/command
```

The staging agent configuration must retain queue `ncdp-staging` and
`hooks-path="/Users/netdevops/.config/buildkite/ncdp-lab/hooks/ncdp-staging"`.
The installed hook must be owned by the agent user, mode `0700`, and sourced
from the reviewed commit before an authorized staging run. Hook updates are an external
operator prerequisite when publishing a reviewed hook update. Hook installation
does not change credential values.

The hook admits only the exact step, queue, canonical repository, retry zero,
and command `.buildkite/scripts/profiled_cml_staging.sh`. The retained hook admission
for PR builds (currently unscheduled) additionally
requires an explicit canonical/non-fork source repository; non-PR runs require
main. Fork or ambiguous origins fail before credentials are sourced. A
maintainer must adopt a runtime-affecting fork change in the canonical repository
and obtain a fresh canonical run to obtain trusted staging evidence.

Only after those checks and file-security validation does the command hook
source the protected `staging.env` beside its installed location. It immediately
requires the job's `BUILDKITE_PIPELINE_ID` to equal the protected
`NCDP_BUILDKITE_PIPELINE_ID` before executing the exact checkout wrapper.
Missing or mismatched identity rejects checkout execution. The expected value
must be declared in the protected file; an inherited job value cannot supply it.
The UUID is the existing immutable subject bound into the OpenBao staging roles,
not a new or rotated identity. The hook is deliberately
not an environment or pre-command hook: repository pre-command hooks finish
before credentials are introduced. Canonical contributors and the agent host
remain trusted personal-lab boundaries; OIDC alone does not make PR code safe.

Before sourcing, the hook requires the protected file to be regular,
non-symlink, agent-owned, and exactly mode `0600`. Its portable mode check
supports GNU/Linux and macOS stat. The containing hook directory must remain
agent-owned and private (mode `0700`). The file supplies these nine names;
never print credential values or commit the file:

- `NCDP_BUILDKITE_PIPELINE_ID` (existing immutable pipeline identifier)
- `NCDP_STAGING_STATE_ROOT`
- `NCDP_NETBOX_URL` and dedicated read-only `NCDP_STAGING_NETBOX_TOKEN`
- `NCDP_OPENBAO_URL`
- `CML2_ADDRESS` and PEM `CML2_CACERT`
- `NCDP_CML_STAGING_USERNAME` and `NCDP_CML_STAGING_PASSWORD`

Ambient AppRole IDs, `NCDP_NETBOX_TOKEN`, `CML2_TOKEN`, and direct device
username/password authority are rejected. The driver validates pipeline/build/job
UUIDs, exact SHA-1 and checked-out bytes through `verify_commit.sh`, branch,
step, queue, and retry before OIDC or CML authentication. During admission the
driver independently compares the pipeline UUID with the required protected
expected value before the commit-verification helper, OIDC request, OpenBao
provider use, or CML authentication.

## Workload identities and prerequisites

One 300-second Buildkite JWT is requested with audience
`urn:ncdp:openbao:staging`, `pipeline_id` as subject, and explicit `build_id`.
It is captured only in process memory. `BuildkiteStagingSecretProvider` retains
the existing exact metadata verification and consumes each device capability
only once, including after a failed exchange:

| Device | JWT role | Sole policy/read path |
| --- | --- | --- |
| 1 core-02 | ncdp-buildkite-staging-device-1 | ncdp-buildkite-staging-device-1-read → ncdp/data/devices/1/ssh |
| 2 edge-junos-01 | ncdp-buildkite-staging-device-2 | ncdp-buildkite-staging-device-2-read → ncdp/data/devices/2/ssh |
| 8 transit-ios-01 | ncdp-buildkite-staging-device-8 | ncdp-buildkite-staging-device-8-read → ncdp/data/devices/8/ssh |
| 9 access-sw-01 | ncdp-buildkite-staging-device-9 | ncdp-buildkite-staging-device-9-read → ncdp/data/devices/9/ssh |

Each role must bind the exact pipeline subject and staging step, map the existing
pipeline/build/commit/branch/step/job metadata, issue only its matching policy,
exclude default and Identity policies, and enforce one token use and TTL limits
of at most 300 seconds. No new role family is introduced.

Existing exact role/policy state is an operator prerequisite. Activation work
does not read secret files or privileged live OpenBao state and does not claim
that static configuration tests prove the live roles. If reconfiguration is
required, an explicitly authorized operator uses the restored thin
`scripts/openbao/configure_buildkite_staging.py` entry point and existing
`OpenBaoBuildkiteStagingConfigurator`, with environment-only administrative
authority. Never invoke it automatically from Buildkite or activation gates.

The personal CML license cannot create a separate narrow staging user. The
protected operator username/password therefore mint exactly one process-memory
bearer over the configured TLS trust. This documented exception is not
least-privilege CML authority. No login fallback, refresh, or automatic retry
exists. The bearer is passed directly to the existing CML reader and recycler;
only bounded Terraform subprocesses receive `CML2_TOKEN`. Operator password
and dedicated NetBox token are removed from the driver environment before
lifecycle subprocesses run.

## Execution, state, and evidence

The authoritative [profiled lifecycle](profiled-disposable-cml-staging.md)
creates exactly one lab, six nodes, nine links, and one lifecycle resource
(17 resources). It independently admits topology and stored management-only
Day-0, performs the separately admitted one-shot CML LAB START,
observes transit's own first boot plus its 60-second persistence interval,
recycles only transit-ios-01 while other nodes can still be starting, and proves
exact realization-scope readiness and strict run-scoped trust, collects read-only device
state, destroys its exact owned graph, proves independent CML absence, and
retires the whole run directory. No CAT8000V, vJunos, or IOSvL2 recycle is
authorized. No network-device CLI write, B4 D1 application, protected delivery,
profiled-deploy authority, or NCDP Live mutation is added.

The driver injects dedicated NetBox and Buildkite JWT providers into
`LocalTerraformOperations`; it invokes the same `ProfiledStagingLifecycle`
used by the local runner exactly once. Local default providers remain unchanged.

The external state root must be absolute, an agent-owned non-symlink directory
outside checkout, and owner-only with required owner read/write/search access
(mode `0700`). Mutable Terraform data, state, backups, saved fenced plans,
verifier-only recovery inputs, and trust live only under:

```text
<state-root>/ephemeral/bk-<build-uuid>/
```

Final schema-v2 `ProfiledStagingEvidence` is create-only mode `0600` at:

```text
<state-root>/evidence/bk-<build-uuid>.json
```

Neither an existing evidence file nor retained run may be reused. The external
filesystem should be encrypted because state and saved plans contain sensitive
Day-0 verifiers. Evidence is outside the disposable run and survives retirement.
Early admission/setup failure can leave an empty reserved evidence file and
private run; neither is success or authority to delete CML resources.

Successful exit requires exact source commit/build/run identity, create and
START success with an exact run-bound lab-start reference, exact run-bound
transit recycle, all four READY, strict trust
generation, all four read-only validations, destroy, absence, retirement, and no
primary or cleanup failure. An incomplete success label is insufficient.

Ordinary logs and the required `cml-staging` annotation contain only closed
lifecycle labels, outcome counts, and failure presence. Raw exception text is
replaced with fixed failure categories in stored evidence. Full schema-v2
evidence stays under the external protected root. On VERIFIED SUCCESS only,
the secret-free schema-v2 bytes are also uploaded as a same-build artifact and
its SHA-256 hash is published as `profiled-cml-success` metadata. Annotation or
artifact failure prevents that success receipt; failed staging never publishes
one. Promotion requires the receipt, not the soft-failed step's scheduling state. JWTs, credentials, bearer tokens, Day-0, Terraform state,
provider bodies, and device configuration are never log or artifact payloads.
Annotation failure after success fails the step; after staging failure it
cannot replace the primary failure.

The summary also renders the schema-v2 closed `timings_seconds` phase durations
for comparison with the former approximately 11-minute job. The lifecycle total
includes nested phases and cleanup, not wrapper setup/publication. Early-recycle
runtime was reported by the user at approximately 8m22s for the successful
lifecycle; failure must not cause a retry or fallback IOSv boot. See the lifecycle document for the
pinned-provider analysis and preserved persistence/readiness waits.

The failed-phase line uses only lifecycle state to select admission,
infrastructure create, CML lab start, transit recycle, service readiness,
strict trust, read-only validation, or cleanup. A primary and cleanup failure
can each be shown without replacing the primary failure. Timing keys remain
unchanged in evidence; human labels replace identifiers only in the summary.
Raw exception/provider bodies never contribute to these labels. The original
PR #136 Terraform START attempt failed before recycle and cleaned up completely;
it is not retried. A new commit/build tests the direct CML lab-start boundary.

## Retained-state recovery

An uncertain CREATE, START, transit STOP/START, or DESTROY is never replayed.
Known owned partial state may proceed through the accepted bounded cleanup;
cleanup ambiguity/failure retains state for operator review. Do not retry the
job, delete CML objects manually, or remove state to obtain a green build.

The existing `scripts/recover_profiled_cml_staging.py` is the separately
authorized destroy-only recovery entry point. It validates the exact retained
run and verifier-only inputs, admits only known managed resources and a saved
exact-delete plan, and retires state only after independent absence. It needs
no OpenBao/device credential read and cannot create or start. Recovery is not
part of automatic Buildkite execution.

## Historical exact-two operations

The retired `scripts/buildkite/ephemeral_staging.sh`, schema-v1 driver,
exact-two topology/readiness, and recovery commands remain historical only in
Git history (for example the parent of `0c24baf`). Their command-hook ordering
and ADR 0027 dependency DAG are operational precedents, not restored runtime
implementations. Historical acceptance documents retain their original meaning.
