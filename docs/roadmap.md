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
4. **Juniper vertical:** the same honest common intent with Junos-native candidate,
   validation, and recovery semantics.
5. **Fleet rollout:** frozen selectors, complete preflight, representative canaries,
   waves, overlap control, no-ops, and honest partial outcomes.
6. **Batfish assurance:** offline parsing and behavioural invariant evidence.
7. **Buildkite approval and hardened deployment:** protected commit/plan binding,
   isolated queues, OIDC, concurrency, artifact promotion, and approval gates.
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
