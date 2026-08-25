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
   independent absence, and guarded state retirement passed. 8E-3 is next and
   adds serialized Buildkite orchestration, staging workload identity, evidence
   publication, and retained-state recovery operations. Parallel twins require
   a future isolated management network.
9. **Recovery and delayed rollback:** vendor-aware immediate recovery, ancestry,
   safe inverse planning, and later-change conflict detection.
10. **Audit/configuration history:** typed `ChangeRecord`, durable correlation, and
    Oxidized Git-backed actual-state chronology.
11. **Continuous observability:** independent metrics, dashboards, alerts, gNMI,
    SNMP, and reachability telemetry.
12. **Final acceptance and demonstration:** mixed-vendor fleet scenario, failure
    cases, recovery, evidence review, security review, and reproducible runbook.
