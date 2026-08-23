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
8. **Terraform/CML infrastructure as code — in progress:** Increment 8A read-only
   discovery and architecture are complete. The 8B foundation and read-only
   plan are accepted after merge: exact toolchain and lock pins, credential-free
   CI validation, provider data-source discovery, external state handling, and
   zero CML mutation. Increment 8C is complete: topology creation,
   `DEFINED_ON_CORE`, controlled `STARTED`, operational `STOPPED`, configuration
   secrecy, and legacy-runtime restoration are accepted. Increment 8D is in
   progress: 8D-1 accepts the IOS XE CML browser console as the one-time manual
   personal-twin bootstrap channel and proves that runtime configuration stays
   outside CML stored configuration and Terraform state and disappears after an
   unsaved restart. Console-keystroke automation was intentionally abandoned as
   low-value for the end-to-end demonstration. Increment 8D-2 accepts persistent
   IOS XE management bootstrap, operational transfer of the unchanged NetBox
   identity from the deliberately stopped legacy realization, unchanged
   OpenBao credential reuse, strict SSH host-trust replacement, existing NCDP
   read-only planning, state secrecy, and restart persistence. Increment 8D-2B
   accepts the ADR 0013 personal-lab Day-0 exception, replacing manual IOS XE
   bootstrap with controlled, zero-console recreation and restart. Strict SSH,
   TCP/830, and existing NCDP read-only planning/preflight succeeded. The exception
   deliberately persists credential-bearing manageability bootstrap in external
   Terraform state and CML Day-0 storage while NetBox and OpenBao remain
   authoritative and NCDP-managed intent stays outside Terraform. Junos Day-0
   bootstrap should reuse the proven pattern. Whole-lab reset/recreate, full
   cutover, and legacy retirement remain. Terraform never manages production or
   NCDP-managed device configuration. See the
   [Terraform/CML digital-twin architecture](architecture/terraform-cml-digital-twin.md).
9. **Recovery and delayed rollback:** vendor-aware immediate recovery, ancestry,
   safe inverse planning, and later-change conflict detection.
10. **Audit/configuration history:** typed `ChangeRecord`, durable correlation, and
    Oxidized Git-backed actual-state chronology.
11. **Continuous observability:** independent metrics, dashboards, alerts, gNMI,
    SNMP, and reachability telemetry.
12. **Final acceptance and demonstration:** mixed-vendor fleet scenario, failure
    cases, recovery, evidence review, security review, and reproducible runbook.
