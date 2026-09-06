# Network Change Delivery Platform

NCDP is a production-inspired personal NetDevOps reference platform for
reviewed, assured, human-authorized, auditable, and observable network changes.
It demonstrates how a network change can move from Git intent to independently
validated Cisco IOS XE or Junos execution without collapsing review, inventory,
credentials, delivery, evidence, and operations into one automation script.

The platform runs on one Mac with a personal CML environment. It has exercised
protected Cisco and Junos live changes, including retained fail-closed and
no-retry evidence, but it is a learning, portfolio, and demonstration system—not
a production deployment template.

## How the platform works

1. **Review intent.** GitHub holds reviewed code, managed intent, plans, policy,
   tests, and pipeline definitions. A pull request has no protected live-write
   authority.
2. **Validate visibly.** Buildkite exposes lint, tests, packaging, runtime
   validation, and pipeline contracts as separate gates that converge at
   `validation-complete`.
3. **Exercise assurance.** The active PR Batfish boundary evaluates the
   profiled four-device candidate without device or credential authority.
4. **Plan and approve explicitly.** `profiled-plan` produces an immutable
   schema-v2 artifact; `profiled-deploy` requires its exact digest and explicit
   `--live` authority.
5. **Execute with vendor semantics.** Python owns policy and orchestration.
   Cisco uses Ansible Runner with `cisco.ios`; Junos uses direct PyEZ/NETCONF
   with an exclusive candidate and commit-confirmed safety.
6. **Validate and preserve evidence.** Fresh independent post-validation decides
   success. AuditStore retains append-only typed evidence, while Oxidized records
   observed actual-state chronology.
7. **Observe independently.** NetBox-bound, CML-admitted Prometheus/Blackbox
   probes feed Grafana and Alertmanager without deployment or remediation
   authority. Monitoring does not end when the pipeline does.

## What it demonstrates

- NetBox-authoritative device, interface, topology, and targeting identity
- OpenBao workload identity and bounded device-credential capabilities
- Cisco IOS XE and Junos planning, execution, validation, and recovery
- Profiled exact-four inventory with explicit operation/capability projections
- Batfish four-device candidate assurance without device-write authority
- Exact-digest local Cisco and Junos execution with immutable schema-v2 evidence
- Historical schema-v1 promotion, fleet, and staging artifacts remain parseable
- Append-only AuditStore correlation and private Oxidized Git chronology
- Persistent Prometheus, Blackbox, Grafana, and Alertmanager visibility
- SNMPv3 synthetic integration and historical protected provisioning evidence,
  without claiming persistent live polling or current provisioning authority

## Safety model

NCDP binds local profiled execution to an immutable schema-v2 plan and exact
operator-approved digest. Immediately before a write, it re-resolves
authoritative identity and checks current device state, profile/operation
support, credential reference, safety, and whether work is still required.

SSH and NETCONF trust are strict and realization-anchored. Vendor behavior is
not flattened: Cisco uses bounded Ansible execution and targeted recovery;
Junos preserves candidate locking and commit-confirmed semantics. If a write
outcome is uncertain, the platform stops and never retries automatically. The
current local profiled path requires independent reconciliation and a new
explicit plan/digest authorization for any corrected attempt. Historical
protected Buildkite delivery additionally required a new commit and build. No
fleet-wide atomicity is claimed.

## Current reference lab

| Area | Current reference implementation |
| --- | --- |
| Purpose | Personal NetDevOps learning, portfolio, and demonstration lab |
| Profile-aware LIVE devices | 4 |
| Managed population | Exact profiled identities 1/2/8/9 |
| Current write projection | Interface descriptions on devices 1/2 only |
| Cisco | `core-02` · IOS XE; `transit-ios-01` · IOS; `access-sw-01` · IOS switching |
| Junos | `edge-junos-01` · Junos |
| Persistent lab | Manually/operator-owned `NCDP Live` in CML |
| Disposable staging | Profiled exact-four implementation pending controlled local acceptance |
| Inventory | NetBox, consumed read-only by automation |
| Credentials | OpenBao with bounded workload/device authority |
| CI/CD | Buildkite validation and profiled four-device PR assurance; no device writes |
| Evidence | AuditStore + exact-four Oxidized actual-state chronology |
| Observability | Exact-four Prometheus + Blackbox + Grafana + Alertmanager |
| Persistent SNMP polling | Deferred |
| gNMI/OpenConfig | Deferred/skipped |

## Deliberate scope

- This is a personal-lab reference implementation, not a production-ready or
  enterprise deployment product.
- It uses no company infrastructure or data and claims no high availability,
  enterprise identity governance, organizational separation, or production scale.
- Continuous observability is read-only and has no autonomous remediation
  authority.
- Persistent live SNMP exporter polling is deferred; accepted SNMPv3 provisioning
  does not imply that polling exists.
- Historical schema-v1 protected delivery and disposable exact-two staging are
  retired. The replacement profiled exact-four staging design is pending
  controlled local acceptance; protected delivery still requires a new profiled
  design.
- IOSv and IOSvL2 are managed exact-four members but do not admit the current
  interface-description write operation.

## Explore

Architecture and operating model:

- [Architecture overview](docs/architecture/overview.md)
- [Buildkite workflow](docs/architecture/buildkite-workflow.md)
- [Change lifecycle](docs/architecture/change-lifecycle.md)
- [Security boundaries](docs/architecture/security-boundaries.md)
- [Recovery safety](docs/architecture/recovery-safety.md)
- [Audit and configuration history](docs/architecture/audit-and-configuration-history.md)
- [Continuous observability](docs/architecture/continuous-observability.md)
- [Architecture decision records](docs/adr/)
- [Current roadmap](docs/roadmap.md)

Selected cumulative acceptance evidence:

- [Increment 7C protected live deployment](docs/acceptance/buildkite-live-deployment-increment-7c.md)
- [Increment 10C-7B protected PRE/write/POST correlation](docs/acceptance/protected-configuration-observation-increment-10c7b.md)
- [Increment 11C SNMPv3 interface telemetry](docs/acceptance/continuous-observability-increment-11c.md)
