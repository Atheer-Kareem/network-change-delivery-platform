# Current roadmap

This roadmap records current increment status and major accepted capability.
Detailed attempt history and fail-closed incident evidence belong in the linked
acceptance records.

## Completed foundation and delivery increments

1. **Repository/executable foundation — complete.** Product and architecture
   contracts, typed CLI/application foundations, deterministic quality gates,
   containers, and CI definition are accepted.
2. **Thin local Cisco vertical — complete.** Reviewed interface-description
   intent, immutable planning, exact execution, independent validation, bounded
   evidence, no-op behavior, and change-specific recovery are accepted. See the
   [Increment 2 acceptance](acceptance/cisco-interface-description-increment-2.md).
3. **NetBox and OpenBao — complete.** NetBox is authoritative for inventory
   identity and OpenBao supplies bounded secret-manager authority.
4. **Junos vertical — complete.** Direct PyEZ exclusive-candidate,
   commit-confirmed execution and independent validation are accepted. See the
   [Increment 4 acceptance](acceptance/junos-interface-description-increment-4.md).
5. **Fleet rollout — complete through 5C.** Frozen selectors, nested plans,
   no-ops, deterministic canaries/waves, complete preflight, strict stop gates,
   whole-fleet validation, mixed-vendor acceptance, and process-local overlap
   admission are implemented. No distributed lock or fleet atomicity is claimed.
6. **Batfish assurance — complete.** Offline provider normalization, exact plan,
   policy, baseline/candidate snapshot and digest binding, typed assurance, and
   protected Buildkite enforcement are implemented.
7. **Buildkite approval and hardened deployment — complete.** Protected
   promotion, human authorization, Buildkite OIDC/OpenBao federation,
   commit-bound least-privilege deployment, independent post-validation, and
   no-retry semantics are accepted. See the
   [Increment 7C acceptance](acceptance/buildkite-live-deployment-increment-7c.md).
8. **Terraform/CML infrastructure and ephemeral staging — complete.** The
   manually owned `NCDP Live` lab remains outside Terraform. Runtime-relevant
   changes use a separate exact ten-resource `.30/.40` staging realization with
   create, start, read-only validation, destroy, independent absence proof, and
   run-scoped state retirement. See the
   [Terraform/CML architecture](architecture/terraform-cml-digital-twin.md) and
   [8E acceptance](acceptance/buildkite-ephemeral-cml-staging-increment-8e.md).
9. **Failure recovery and change-aware CI — complete.** Vendor-aware immediate
   recovery, ambiguous-write stop behavior, strict fleet stop semantics, and
   fail-closed runtime-path classification are implemented. Historical rollback
   remains a new reviewed desired-state change, not a replay.

## Audit and configuration chronology

10. **Audit/configuration history — complete through accepted protected
    Oxidized/audit correlation scope.** Append-only `ChangeAuditRecord` and
    `ConfigurationObservationRecord` persistence, Buildkite correlation,
    private Git-backed Oxidized chronology, NetBox/OpenBao materialization,
    persistent service ownership, CML-anchored trust, strict Cisco/Junos
    collection, and protected PRE/write/POST correlation are accepted.
    `TEMPORALLY_BRACKETED` chronology remains honest `NOT_PROVEN` causality.
    The fail-closed attempts leading to Build #158 remain in the
    [10C-7B acceptance record](acceptance/protected-configuration-observation-increment-10c7b.md),
    rather than in this current roadmap.

## Continuous observability

11. **Independent read-only observability — accepted through 11C-3.**

    - **11A — complete:** persistent Prometheus and credential-free Blackbox
      management-service probes use stable NetBox identity plus exact `NCDP
      Live` realization admission. Build #215 accepted the persistent path.
    - **11B — complete:** provisioned Grafana, reviewed Prometheus rules,
      Alertmanager, and a bounded local demonstration receiver provide advisory
      visibility without remediation authority. Build #231 and persistent
      runtime acceptance closed 11B.
    - **11C-1 — complete:** reviewed SNMPv3 architecture, exact generated
      standard-IETF module, stable interface identity, and offline contracts.
    - **11C-2 — complete synthetic integration only:** the opt-in disposable
      exporter overlay proves SNMPv3 `authPriv`, two-network separation,
      rotation, normalization, and secret-leak controls. It does not alter the
      accepted persistent five-service runtime or prove live-router polling.
    - **11C-3 — complete:** separately authorized protected live provisioning
      succeeded for Cisco Build #267 (`CHG-SNMP-11C3-CISCO-004`) and Junos Build
      #275 (`CHG-SNMP-11C3-JUNOS-001`). Junos used prior disposable `.40`
      rehearsal of the exact source plan. Build #273 remains non-retried
      fail-closed evidence. See the cumulative
      [11C acceptance record](acceptance/continuous-observability-increment-11c.md).
    - **11C-4 — deferred:** persistent exporter materialization, activation,
      Docker-to-live-router UDP/161 evidence, and live polling are not claimed.
    - **11D — deferred/skipped:** gNMI/OpenConfig is not the next active
      increment for this reference implementation.

## Final acceptance, usability, and presentation

12. **Final acceptance and demonstration — in progress.** This is refinement of
    the completed feature set, not a new feature increment after 11C-3.

    - **12A — complete:** validation gates are individually visible and join at
      `validation-complete`; Buildkite definition validation is separate from
      the NCDP pipeline safety contract; Batfish assurance is first-class and
      fans out with CML staging; immutable promotion joins both; and the single
      serialized staging lifecycle exposes create → validate → destroy phases
      plus sanitized typed annotations. The personal validation agent currently
      uses bounded two-worker capacity as a local operational setting, not a
      portable architecture requirement.
    - **12B — complete:** authoritative product, architecture, roadmap, ADR,
      and cumulative acceptance documents are reconciled with accepted current
      truth.
    - **12C — complete:** README is the concise public front door, supported by
      a repository-hosted flagship architecture visualization of current
      authority, staging, assurance, delivery, evidence, and observability
      boundaries.
    - **12D — complete:** a browser-first native-surface audit established the
      demonstration boundary; a curated safe-surface catalog records primary,
      supporting, and avoided views; and a minimal foreground, loopback-only
      viewer presents validated durable audit and metadata-only configuration
      chronology without becoming a control plane.
    - **12E — next:** readiness, reset, and evidence package.
    - **12F — planned:** demonstration runbook and rehearsal.
    - **12G — planned:** final acceptance and repository closure.
