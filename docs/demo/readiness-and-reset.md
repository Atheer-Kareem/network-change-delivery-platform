# Demonstration readiness and safe reset

> **“Reset” means restoring demonstration usability, not resetting network
> state.** Never erase or recreate authority, evidence, topology, or device state
> merely to make the demonstration look fresh.

Five minutes before the walkthrough, from clean `main`, run:

```console
uv run ncdp-demo-readiness --audit-root <existing-private-audit-root>
```

The command is read-only. `PASS` and `FAIL` are automated local results;
`MANUAL` preserves browser/authentication boundaries; `OPTIONAL` identifies a
presentation convenience that is not platform readiness. It neither fetches Git
nor starts services. Resolve failures through the bounded ownership paths below,
then rerun the command.

## Safe presentation reset

- Stop a foreground evidence viewer with Ctrl-C and restart it with
  `uv run ncdp-evidence-viewer --audit-root <existing-private-audit-root>`.
- Refresh or reopen the curated tabs in [browser surfaces](browser-surfaces.md).
- Use normal non-destructive Git workflow: inspect with `git status`, switch to
  `main`, and update only with an ordinary fast-forward workflow before the
  readiness check. Never reset, clean, or discard unknown work for a demo.
- Start Docker Desktop manually if it is not running. Do not make the readiness
  command start it.
- Rerun `ncdp-demo-readiness`; do not “fix” a MANUAL result by weakening
  authentication or TLS.

## Persistent local services

NetBox, observability, and Oxidized are owned by separate scheduled launchd
jobs: `com.ncdp.netbox-lab`, `com.ncdp.observability`, and
`com.ncdp.oxidized`. A read-only `launchctl print gui/<uid>/<label>` inspection
may confirm that the accepted owner is loaded. Their reviewed `ensure` wrappers
and five-minute `StartInterval` perform normal reconciliation.

| Service | Safe verification | Accepted reconciliation/update ownership |
| --- | --- | --- |
| NetBox | `launchctl print gui/<uid>/com.ncdp.netbox-lab`; readiness checks the loopback UI | launchd invokes the installed `ensure`; [`scripts/netbox/update_service_runtime.sh`](../../scripts/netbox/update_service_runtime.sh) is only for publishing a reviewed source update |
| Observability | `launchctl print gui/<uid>/com.ncdp.observability`; readiness checks Grafana and Prometheus | launchd invokes the installed `ensure`; [`scripts/observability/update_service_runtime.sh`](../../scripts/observability/update_service_runtime.sh) is only for a reviewed source update |
| Oxidized | `launchctl print gui/<uid>/com.ncdp.oxidized`; inspect ownership only during readiness | launchd invokes the installed `ensure`; [`scripts/oxidized/update_service_runtime.sh`](../../scripts/oxidized/update_service_runtime.sh) is only for a reviewed source update |

The repository `install_service.sh` scripts are first-install operations, not
recovery commands. The `update_service_runtime.sh` scripts publish a reviewed
new source runtime and are not a five-minute presentation reset. Do not invoke
either class casually. Let the existing launchd owner reconcile; if it cannot,
stop and investigate the bounded service rather than recreating volumes or
state. The readiness command checks only the public loopback surfaces and never
invokes these reconcilers.

OpenBao has its own accepted local ensure/unseal ownership outside these three
repository installers. Use the unauthenticated health result to diagnose its
state; do not bypass that owner or expose unseal material.

## CML live lab

`NCDP Live` is persistent, manually/operator-owned CML state and is outside
Terraform. Never Terraform-destroy it, recreate it as a reset, or create a
second live lab. If the exact accepted lab is stopped, verify its identity in
the CML UI and use the UI to start that realization only. Confirm `core-02` and
`edge-junos-01` are both `BOOTED`; do not edit node configuration.

## Ephemeral staging

Normal Buildkite staging owns its complete create → read-only validate → destroy
lifecycle. Do not create a staging twin before the demo and do not delete
arbitrary CML labs. A retained failed run is recovered only with the exact
run-scoped state and the guarded command documented in
[Buildkite ephemeral staging operations](../architecture/buildkite-ephemeral-cml-staging-operations.md#retained-state-recovery).
Never perform generic Terraform state surgery.

## OpenBao

Do not rotate working credentials, recreate auth methods, generate new
SecretIDs, or mint presentation tokens to “freshen” the demo. The native UI is
available only through the existing loopback listener at
`http://127.0.0.1:8200/ui/`; it requires existing authorized OpenBao
authentication and does not replace AppRole/OIDC machine authentication.

## AuditStore and Oxidized

Never clear AuditStore, prune the private Oxidized Git chronology, or trigger a
collection merely to create a recent timestamp. Historical accepted evidence is
deliberately durable. The viewer and readiness command open the existing store
with `create=False`; neither is an evidence publisher.

## Buildkite

Never retry a historical deployment job and never authorize a pending block to
make the demo look active. An uncertain or corrected attempt requires a new
commit, build, and authorization. Buildkite browser history is presentation;
AuditStore remains durable evidence authority.

### Explicit DEMO CONTINUE mode

**Normal CI remains hard-fail. Demo mode is presentation-only, not acceptance
evidence for merging or delivery.** Do not treat a green demo aggregate as
proof that validation, Batfish, or CML passed; inspect their truthful evidence.

One-time operator prerequisite, after this source is reviewed and available on
`main`: in Buildkite **Settings → Steps**, use the YAML steps editor and change
the existing pipeline-upload command to:

```sh
uv run --frozen python scripts/buildkite/render_demo_pipeline.py --upload
```

Keep that bootstrap on `ncdp-validation`, hard-fail, with automatic and manual
retries disabled. Do not install a repository hook or touch the staging-agent
hook/environment. This is a pipeline bootstrap setting, not a GitHub ruleset or
required-status change. The implementation does not update live settings.
Until the operator changes that bootstrap, the existing direct upload continues
to run the normal hard-fail graph even when the demo variable is supplied.
Do not change the bootstrap before the script is on main; older checkouts lack it.

Then start each demonstration from the Buildkite UI:

1. **New build**.
2. Branch: **main**, using the reviewed main commit, without PR context.
3. Set **`NCDP_DEMO_CONTINUE_ON_FAILURE=1`** in this build's environment.
4. **Start build**. Do not retry an earlier build or step.

Never set the flag globally on the pipeline or agent. Only exact value `1`,
source `ui`, branch `main`, and no pull request are admitted. The renderer also
requires canonical repository, validation queue and retry zero, and rejects
contradictory PR metadata, tags and triggered-build metadata. API, webhook,
schedule, trigger-job, other branches, and missing/invalid explicit values
cannot render a demo. A nonempty invalid demo request fails the bootstrap
before annotation/upload. An unset/empty flag uploads `.buildkite/pipeline.yml`
directly with the existing `--fetch-diff-base` change detection; no production
graph transformation or banner occurs.

The renderer derives the current 15 command steps plus validation wait from
the reviewed normal graph; it rejects new/unknown shapes rather than silently
softening them. Demo commands carry a server-side `build.source == "ui"`,
`build.branch == "main"`, no-PR and exact-flag conditional as well. They preserve
commands, keys, queues, dependencies, concurrency, explicit retry prohibitions,
and credential boundaries. Missing retry defaults are closed to disabled for
demo only. Demo suppresses all `if_changed` filters, and replaces the PR-only
Batfish conditional only with the strict demo conditional. Batfish independently
admits canonical PR or manual-main demo before Docker/commit work; its decision
and full evidence are unchanged.

One warning annotation, **DEMO MODE — CONTINUE ON FAILURE**, is published before
the demo upload. Command labels have a short `DEMO ·` prefix. Every generated
command has `soft_fail: true`; the validation wait has
`continue_on_failure: true`. Soft-failed dependencies already permit downstream
execution, so there is no `allow_dependency_failure` override. See Buildkite's
[soft-fail semantics](https://buildkite.com/docs/pipelines/configure/soft-fail)
and [wait semantics](https://buildkite.com/docs/pipelines/configure/step-types/wait-step).
The installed agent `3.137.0` accepts both graphs with `--dry-run --format yaml
--reject-secrets --reject-parse-warnings`; this is static validation, not runtime
acceptance.

An application failure stays FAILED with its real nonzero exit code and evidence;
Buildkite presents it as SOFT FAILED and continues validation → Batfish → CML.
Bootstrap admission, annotation and upload errors remain hard failures: an
unlabeled or incomplete demo is not silently accepted. Cancellation, unavailable
agents and infrastructure outages are not converted into successful execution.

The trusted CML hook, pipeline binding, staging.env permissions, exact devices
1/2/8/9, OpenBao roles, one-shot lab START, transit-only recycle, cleanup and
no-device-write rules are unchanged. Failed cleanup still retains state, and
the existing recovery runbook applies before any new run. No protected delivery
or NCDP Live write is added. Normal webhook PR/main builds retain their hard-fail
graph and existing aggregate required-status merge gate. Demo success must not
be cited as normal CI, merged-main staging, or delivery acceptance.

## Docker

Starting Docker Desktop manually is safe presentation recovery. Volume pruning,
broad image cleanup, and `docker compose down -v` against persistent platform
services are not. Do not stop unrelated containers or merge validation,
staging, and deploy-agent authorities.
