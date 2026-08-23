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
7. **Buildkite approval and hardened deployment — in progress:** 7A is complete,
   including external protected-main Buildkite acceptance of offline promotion
   artifacts, exact human-approved digests, isolated queue routing, and the
   serialized no-write deployment gate. 7B is complete, including its
   application boundary, main-only gate integration, reproducible JWT-role
   operator tool, and protected-main external Buildkite/OpenBao federation
   acceptance. Increment 7 remains in progress. 7C-A implements the commit-bound,
   single-device, least-privilege live-deployment foundation without an active
   request or live write. External 7C live CML acceptance remains pending.
8. **Terraform/CML infrastructure as code:** reproducible twin lifecycle and reset,
   without Terraform-managed production configuration.
9. **Recovery and delayed rollback:** vendor-aware immediate recovery, ancestry,
   safe inverse planning, and later-change conflict detection.
10. **Audit/configuration history:** typed `ChangeRecord`, durable correlation, and
    Oxidized Git-backed actual-state chronology.
11. **Continuous observability:** independent metrics, dashboards, alerts, gNMI,
    SNMP, and reachability telemetry.
12. **Final acceptance and demonstration:** mixed-vendor fleet scenario, failure
    cases, recovery, evidence review, security review, and reproducible runbook.
