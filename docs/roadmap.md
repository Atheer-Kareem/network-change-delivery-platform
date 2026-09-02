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
    - **12E — complete:** a read-only demonstration readiness checker, safe
      reset/recovery contract, and canonical historical/live evidence package
      make final-demo preparation predictable without recreating state.
    - **Detour A — in progress before 12F:** runtime-relevant pull requests are
      being hardened to require Batfish candidate assurance before trusted
      disposable CML staging, while protected main independently re-verifies
      both branches.
    - **Detour B — complete through B5-3:** B1 accepts the
      additive multi-device profile, management, authority, and managed-state
      contracts. B2 adds a parallel profile-aware read-only NetBox provider,
      LIVE-only target projection, and exact profile-bound Cisco/Junos
      collection without changing v1 delivery. Evidence established that the
      accepted CAT8000V key remains valid and that pinned libssh trust-source
      handling—not stale trust—was the blocker. ADR 0029 accepts explicit
      Paramiko admission for all three Cisco profiles without fallback or
      algorithm relaxation. B3-1 separates the legacy `ncdp-managed`
      population from exact `ncdp-profiled-inventory` membership and defines
      additive four-device realization, CML-anchored trust metadata, and
      run-scoped STAGING-only projection. B3-2 migrates local NetBox authority:
      new stable devices 8/9 were created planned, management purpose is explicit,
      and the four approved physical cables are recorded while legacy devices
      1/2 and their runtime consumers remain exact-two. B3-3 stores distinct SSH
      credentials for devices 8/9, extends local and staging read authority to
      exact IDs 1/2/8/9, and temporarily pauses both automatic CML staging and
      protected delivery while preserving quality, Terraform validation, and PR
      Batfish. The paused pipeline blocks remain disabled until the operator
      explicitly decides disposable CML staging is useful again and its
      Terraform topology is ready for the intended profiled population; both
      blocks must then be restored together. B3-4 accepts the operator-owned
      four-device `NCDP Live` realization, a separate CML-anchored exact-four
      trust generation, activation of devices 8/9, and real profile-aware LIVE
      read-only collection for all four. Legacy inventory, Oxidized,
      observability targets, SNMP, and protected authority remain exact devices
      1/2. B3-5 establishes the exact NetBox-owned `10.60.0.0/16` hierarchy,
      three routed-link prefix/interface/IP relationships, VLAN 10 `USERS`,
      VLAN 20 `SERVERS`, and the then-unallocated routing-identity pool. A closed
      GET-only profiled resolver admits only those exact factual objects; no
      network-device data-plane configuration is applied. Four-device
      disposable STAGING realization and STAGING adapter
      acceptance remain deferred until explicit operator restoration is useful.
      B4-1 turns the three routed-link allocations into the first Git-owned
      service intent: exact read-only O, normalized proposed D1, deterministic
      IOS XE/IOS/Junos O-to-D1 change rendering, and a separate exact-four
      D1-only Batfish candidate assurance model. The observed legacy
      `10.6.12.0/30` on the core/Junos link remains an explicit delta and is
      explicitly removed by the proposal artifact while remaining absent from
      the final-state candidate. No routed-underlay configuration was applied,
      and live application remains deferred while protected delivery is
      disabled. B4-1A hands the single active PR Batfish step from the legacy
      v1 two-device promotion baseline to a deterministic offline profiled
      four-device assurance record. B4-2 allocates exact unassigned NetBox
      router-ID identities and adds OSPF intent, real read-only observation,
      O-to-D1 rendering, and combined `routed_underlay + ospf` assurance. The
      router IDs are not loopbacks or advertised routes. Live application
      remains deferred while protected delivery is disabled. B4-3 allocates
      exact planned core VLAN subinterfaces/gateways, adds VLAN intent and real
      read-only observation, and assures router-on-a-stick plus access switching.
      Its active Batfish model keeps four managed network devices and adds two
      assurance-only host fixtures to prove gateway and bidirectional pre-ACL
      inter-VLAN behavior through core; no endpoint NetBox/CML authority or
      network write is created. Legacy protected
      assurance remains preserved and disabled; no protected promotion or
      execution authority was migrated. B4-4 adds one exact directional
      USERS-to-SERVERS ACL intent, bounded read-only observation,
      observation-bound IOS rendering, and differential Batfish assurance:
      HTTPS remains permitted, SSH/ICMP are denied outbound at core, and
      reverse traffic and gateway reachability remain permitted. No ACL was
      applied to LIVE. B5-1 adds envelope-scoped canonical state projections,
      a private append-only per-vertical acceptance chain, deterministic v1
      `AcceptedManagedStateRef` resolution, and distinct D0/O, D0/D1, and O'/D1
      comparison semantics. It does not treat any B4 proposal as D0 and does
      not initialize a real store. B5-2 adds the commit-bound, continuity-gated,
      two-pass LIVE initializer: four independent generation-one records are
      staged together, second-pass O must equal D0 for every vertical, and only
      then may the complete private store be atomically promoted. The exact
      adoption evidence records the one-shot operator run; no B4 proposal is
      silently promoted to D0.
      The accepted run created exactly four generation-one records, then proved
      second-pass `O == D0` for all four. B5-3 exercised controlled drift with
      two manual running-configuration transitions on
      `transit-ios-01/GigabitEthernet0/1`: `no shutdown` produced
      `DRIFT_DETECTED`, and `shutdown` restored D0. Pre-drift and recovery were
      `IN_SYNC` for all four; every D0/D1 comparison remained
      `CHANGE_PROPOSED`; NCDP-authorized writes were zero. The persistent D0
      store remained unchanged. Disposable CML staging and protected delivery
      remain paused. The operator subsequently restored observability runtime
      and synthetic SNMPv3 validation as active Buildkite quality steps. Both
      are temporarily `soft_fail` while their Buildkite-runtime behavior is
      reconciled after Detour B; the observed duplicate management-runtime
      Docker identity collision is avoided by disabling the synthetic step's
      nested observability regression in Buildkite only. Successful local
      runtime validation is not evidence of Buildkite success, and remaining
      runtime failures are separately bounded work. The synthetic two-agent
      fixture validates protocol behavior only; it is not completion evidence
      for the separate live SNMP exact-four migration, whose target is all four
      profiled devices.
      The exact-two legacy path and profiled exact-four path are transitional
      coexistence, not the target end state: final NCDP is one profiled
      exact-four managed fleet with explicit profile/capability gating. Legacy
      `ncdp-managed` remains while its legitimate consumers are migrated to the
      profiled architecture. A consumer may be retired instead only through an
      explicit decision that its capability is obsolete or outside final NCDP
      scope. The legacy path is removed only after no legitimate runtime
      consumer remains. The first bounded migration increment changes NetBox
      lifecycle/readiness only; it leaves all other legacy consumers and tags
      intact. The second bounded migration increment migrates
      management-service observability: its target generation, persistent CML
      realization admission, and readiness contract now bind the profiled
      exact-four population. The operator then restored its runtime validation
      and synthetic SNMPv3 validation as active, temporarily soft-failing
      quality steps; other legacy consumers remain unchanged.
    - **12F — on hold:** demonstration runbook and rehearsal.
    - **12G — planned:** final acceptance and repository closure.
