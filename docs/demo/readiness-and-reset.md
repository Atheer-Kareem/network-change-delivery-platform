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
SecretIDs, or mint presentation tokens to “freshen” the demo. Optional future
loopback UI enablement is a separate operator enhancement; it is not a reset and
does not replace AppRole/OIDC machine authentication.

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

## Docker

Starting Docker Desktop manually is safe presentation recovery. Volume pruning,
broad image cleanup, and `docker compose down -v` against persistent platform
services are not. Do not stop unrelated containers or merge validation,
staging, and deploy-agent authorities.
