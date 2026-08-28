# Dependency-based roadmap

Each increment begins only when predecessor contracts and evidence justify it.
Ordering may change when implementation evidence requires it.

1. **Repository/executable foundation — complete:** product and architecture contracts,
   CLI shell, deterministic quality gates, container foundations, and CI definition.
2. **Thin local Cisco vertical — complete:** executed typed interface-description intent on
   one manually prepared personal CML IOS XE target using synthetic, non-company
   data. Acceptance covered preflight, immutable digest approval, exact-artifact
   execution, independent post-validation, bounded evidence, and a read-only
   idempotency no-op; tested change-specific Cisco recovery semantics remain in
   place, although successful live validation did not require recovery. See the
   [live acceptance report](acceptance/cisco-interface-description-increment-2.md).
   Terraform-managed CML topology and lifecycle remain increment 8.
3. **NetBox and OpenBao — complete:** NetBox provides authoritative inventory
   identity and OpenBao AppRole provides short-lived, least-privilege
   secret-manager access to the static lab device credential. Buildkite JWT/OIDC
   and stronger or dynamic device authorization remain later work.
4. **Juniper vertical — complete:** the common interface-description intent,
   direct-PyEZ exclusive candidate validation, commit-confirmed lifecycle, and
   bounded evidence are implemented. Real vJunos read-only discovery, immutable
   plan review, exact-digest commit-confirmed execution, independent validation,
   confirmation, and read-only idempotency acceptance are recorded in the
   [Increment 4 acceptance report](acceptance/junos-interface-description-increment-4.md).
5. **Fleet rollout — complete through Increment 5C:** Increment 5A implements frozen narrow NetBox
   selectors, nested immutable child plans, first-class no-ops, canonical fleet
   digests, deterministic representative canaries and fixed waves, and complete
   fleet-wide read-only preflight. Increment 5B implements digest-approved
   sequential exact canary/wave execution through the existing device workflow,
   strict stop gates, honest partial evidence, and final whole-fleet read-only
   validation and is complete. Increment 5C adds process-local same-device
   overlap admission and has completed mixed-vendor live CML acceptance,
   including exact canary/wave execution, final validation, and a read-only
   idempotency check proving three compliant members and zero deployable work.
   Distributed/cross-run locks, runner concurrency groups, and multi-worker
   coordination remain in the later Buildkite hardening increment; they do not
   replace local rollout overlap safety.
6. **Batfish assurance — complete after review/merge:** Increment 6A
   establishes the offline provider and behavioral evidence boundary. Increment
   6B binds exact validated plans, policy, frozen baseline bytes, derived
   candidates, and self-digested assurance records. Deployment enforcement and
   provenance remain Increment 7.
7. **Buildkite approval and hardened deployment — complete:** 7A completed
   protected promotion and exact human approval; 7B completed real Buildkite
   OIDC-to-OpenBao federation; and 7C completed commit-bound, least-privilege,
   single-device protected deployment. External acceptance includes a real CML
   IOS XE write and independent validation, deployment-runtime prerequisite
   verification before privileged identity, prohibition of same-build
   deployment-job retries, and protected-main acceptance of the unchanged-request
   no-write path. See the
   [Increment 7C acceptance report](acceptance/buildkite-live-deployment-increment-7c.md).
8. **Terraform/CML infrastructure as code — Increment 8D complete:** Increment 8A read-only
   discovery and architecture are complete. The 8B foundation and read-only
   plan are accepted after merge: exact toolchain and lock pins, credential-free
   CI validation, provider data-source discovery, external state handling, and
   zero CML mutation. Increment 8C is complete: topology creation,
   `DEFINED_ON_CORE`, controlled `STARTED`, operational `STOPPED`, configuration
   secrecy, and legacy-runtime restoration are accepted. Increment 8D records
   the Day-0 manageability investigation: IOS XE first-boot automation was
   accepted; vJunos fresh-first-boot automation and the exact customizer payload
   were proven independently; and explicit replacement of the lab, five nodes,
   six links, and lifecycle resource proved a complete Terraform reset/recreate.
   The same vJunos realization did not preserve management connectivity across
   restart, so persistent 8D-3 acceptance failed. ADR 0014 supersedes that
   staging model with an ephemeral lifecycle, and the current Terraform twin
   was completely destroyed. Terraform never manages production or NCDP-managed
   device configuration. See the
   [Terraform/CML digital-twin architecture](architecture/terraform-cml-digital-twin.md).
   **Increment 8E — Ephemeral CML staging pipeline** is split into explicit
   stages. 8E-1 provides the reusable Terraform realization module, protected
   operator root, intentionally destroyable ephemeral root, required run
   identity, build/run-scoped state contract, safe outputs, and credential-free
   static validation. 8E-2 is locally accepted: fresh creation, first-boot
   readiness, both read-only NCDP vendor chains, direct destroy from STARTED,
   independent absence, and guarded state retirement passed. 8E-3 adds the
   serialized Buildkite gate, staging workload identity, dedicated read-only
   authority boundaries, trusted-agent PR admission, evidence publication, and
   retained-state recovery. Increment 8E-3 is complete: PR #44 merged and the
   merged commit passed Buildkite build #115, including the ephemeral CML staging
   gate before promotion. Parallel twins require a future isolated management
   network.
9. **Failure recovery — complete:** vendor-aware immediate recovery,
   failed-validation handling, honest ambiguous-write behavior, recovery
   verification, and strict fleet stop semantics. Sophisticated historical
   rollback with ancestry, automatic inverse planning, and later-change conflict
   detection is deferred; a later rollback is a new reviewed desired-state
   change through the ordinary delivery pipeline. The subsequent change-aware
   Buildkite optimization is also complete: known documentation, test, and
   repository-metadata-only changes retain quality/status checks while live
   staging and protected delivery remain fail-closed for every runtime-relevant
   or unknown path.
10. **Audit/configuration history:** split to preserve existing evidence
    semantics and separate metadata durability from sensitive actual-state
    chronology. **10A — audit architecture and durable-correlation contract**
    defines the evidence inventory, a top-level correlation envelope, external
    append-only storage, authority boundaries, and the Oxidized integration
    boundary. **10B-1 — durable audit models and append-only store** implements
    the typed envelope, reviewed artifact references, canonical integrity,
    bounded filesystem persistence, no-overwrite publication, and validated
    programmatic reads independently of deployment. **10B-2 — Buildkite
    correlation and CLI query integration** implements same-build semantic
    correlation, a pre-write durable-store gate, honest post-outcome audit
    failures, and bounded `show`/`find` reads without Oxidized. **10C —
    Oxidized Git-backed actual-state chronology and audit correlation** will add
    private external Cisco/Junos configuration history, bounded collection, and
    non-secret Git references without changing desired intent authority.
    **10C-1 — offline configuration-observation contracts and append-only
    correlation persistence** adds a separate metadata-only follow-up record,
    exact parent UUID/digest linkage, and bounded reads and queries without
    installing or running Oxidized. 10A, 10B-1, and 10B-2 are complete; 10C-1
    is complete. **10C-2 — reproducible Oxidized runtime packaging** freezes a
    digest-pinned, non-root Apple-Silicon OCI runtime for Oxidized 0.37.0 and
    oxidized-web 0.18.1 and proves a loopback-only synthetic API without device
    collection. NetBox/OpenBao materialization, private Git chronology,
    persistent service ownership, scheduling, and forced observation remain
    later 10C increments. **10C-3 — NetBox/OpenBao source materialization** adds
    the host-side exact-population authority resolver, dedicated read-only
    OpenBao identity, atomic private JSONFile cache, and no-collection parser
    proof. **10C-4 — private Git chronology** proves Oxidized's bare Rugged
    writer, unchanged-byte suppression, multi-node path chronology, and a
    metadata-only path-scoped `OxidizedRevision` reader in disposable synthetic
    state. **10C-5 — persistent Oxidized service and collection control plane**
    adds launchd-owned repository-independent reconciliation, a direct private
    Git bind mount, source-freshness readiness, minimal OpenBao machine
    bootstrap, and bounded per-node control while interval zero keeps real
    collection disabled. Its reboot acceptance is operator-triggered; real
    baseline collection remains 10C-6. **10C-6 — strict live configuration
    chronology** adds CML-anchored fresh SSH host trust, readiness schema 2,
    SSH-only secure collection, path-scoped collection/revision binding, the
    first private Cisco and Junos baseline commits, unchanged-observation
    suppression, trust retirement, and fixed-address CML cleanup. Protected
    pre/post change and audit correlation remains 10C-7. **10C-7A — protected
    observation-correlation preparation** adds the offline adapter, same-job
    PRE/deploy/POST ordering, immutable parent/child persistence, and a new
    commit-bound Cisco change. Real protected execution and durable live
    correlation remain pending merged-main 10C-7B acceptance. Build #150 failed
    safely before PRE or any device write when its reboot-persistent deploy
    environment omitted the intact accepted Ansible collection root. The
    corrected path guard and comment-only retry authorization 1 produced Build
    #152, which reached PRE and failed closed because its required post-merge
    operator twin, realization trust, and schema-2 readiness had not been
    prepared before approval. Neither failed build performed a device write or
    created observation/audit evidence; both are permanently non-retriable.
    Comment-only retry authorization 2 produced Build #154, which was prepared
    and authorized. Its successful PRE collection created a legitimate third
    private-history revision, but durable conversion rejected the Git timestamp
    because it followed the upstream job end by one second. The gate stopped
    before deployment and created no audit evidence. Build #154 is permanently
    non-retriable. The corrected durable completion boundary and comment-only
    retry authorization 3 prepare another semantically identical attempt. Real
    acceptance remains pending fresh post-merge runtime preparation and
    explicit approval of only that new main build. Build #156 then completed
    PRE, created a legitimate fourth private-history commit, and reached the
    device-capable boundary. Fresh NetBox and one-use OpenBao resolution
    succeeded, but read-only deployment preflight used a stale generic-user SSH
    key instead of the accepted realization trust, so execution remained
    unattempted and device writes remained zero. Its immutable `BLOCKED` parent
    and successful CHANGED/UNCHANGED temporally bracketed child were persisted.
    Protected deployment now projects validated realization trust into its
    private Ansible runtime; retry authorization 4 prepares the next
    semantically identical attempt. Build #158 completed that attempt: PRE,
    protected Cisco execution, independent post-validation, and POST succeeded;
    the immutable parent and temporally bracketed child validate as
    `SUCCEEDED`, with causality correctly retained as `NOT_PROVEN`. Trust and
    readiness were then retired and the exact operator twin destroyed while
    preserving six private-history commits. Increment 10C-7B is complete. No
    later increment has started.
11. **Continuous observability:** an independent, read-only operational plane.
    Architecture evidence during 11A reordered its live-acceptance dependency:
    ADR 0023 now requires a persistent manually owned brownfield live/reference
    pair and separately identified, addressed, credentialed, Terraform-owned
    ephemeral staging. This migration is a bounded prerequisite rather than a
    restart or failure of 11A:
    - **Phase A — architecture authority:** ADR 0023 defines brownfield live,
      isolated ephemeral staging, explicit scenarios, partial managed-intent
      ownership, admission without Terraform ownership, and phased migration.
      It changes documentation only.
    - **Phase B — staging separation:** perform management-network feasibility,
      establish staging NetBox identities and homolog authority, staging IPAM
      and credentials, reduce the Terraform baseline to the Cisco/Junos pair,
      and accept separated ephemeral staging. Phase B1-1 correctly stopped when
      external allocation authority was unavailable. A later bounded follow-up
      recorded the operator-confirmed static/no-DHCP policy and established the
      `192.168.4.0/24` NetBox Prefix plus known infrastructure allocations;
      subsequent read-only collision discovery and human selection admitted
      `.30`/`.31`. B1-2 is complete: stable
      staged devices 6 and 7 use a dedicated role, explicit `staging` environment
      and live-homolog fields, separate primary IPs, and no live selector tags;
      canonical devices 1 and 2 are explicitly `live`, while device 3 remains
      unclassified. Native NetBox provenance records both bounded writer episodes,
      and both temporary writers were retired with zero standing privilege. B2
      is externally complete pending repository review: separate KV-v2 secrets,
      exact policies, and staging JWT roles now belong to devices 6/7; bounded
      administrative capability matrices deny live and sibling paths; and the
      historical staging roles/policies for live devices 1/2 are retired. Live
      secrets and deployment authority remain unchanged. The checked-in staging
      consumer still targets 1/2 and is deliberately fail-closed. Before any B3
      source or Terraform commit, a reviewed Buildkite migration execution guard
      or freeze must prevent legacy `cml-staging` execution. Terraform/Buildkite
      consumer migration remains unstarted.
    - **Phase C/D — brownfield rehabilitation and onboarding:** freshly inspect
      and privately protect recovery evidence, manually remove only approved
      obsolete resources, observe before remediation, reconcile authority,
      establish realization admission and strict trust, and capture the live
      actual-state baseline.
    - **Phase E/F — consumer cutover and obsolete-contract retirement:** move
      11A, Oxidized continuous operation, then protected deployment; afterward
      remove disposable operator-lifecycle and shared-address assumptions.
    Every phase remains fail closed with an explicit stop boundary. No migration
    implementation or infrastructure mutation is part of Phase A.

    Phase 11 remains decomposed into these bounded increments:
    - **11A — NetBox-bound management-service reachability:** persistent
      Prometheus and credential-free Blackbox TCP probes with stable NetBox
      identity and realization-scoped CML admission. Implementation is complete
      through its current reviewed contracts, including persistent runtime,
      source binding, CML 2.10 parsing, TSDB retention, and bounded refresh
      diagnostics. Final acceptance is explicitly paused for the ADR 0023
      environment migration; no further disposable operator-twin attempt is
      authorized.
    - **11B — dashboards and operator-only alerts:** bounded visualization,
      reachability/staleness/service-health rules, and no remediation authority.
    - **11C — SNMPv3 interface telemetry:** least-privilege authenticated polling
      and bounded interface identity/counter normalization.
    - **11D — gNMI/OpenConfig streaming telemetry:** reviewed TLS identity,
      vendor-aware capability admission, and streaming normalization.
12. **Final acceptance and demonstration:** mixed-vendor fleet scenario, failure
    cases, recovery, evidence review, security review, and reproducible runbook.
