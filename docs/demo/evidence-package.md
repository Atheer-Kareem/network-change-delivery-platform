# Canonical demonstration evidence package

This is the definitive evidence selection for the later Increment 12F runbook.
It contains pointers and interpretation, not copied screenshots or raw
artifacts. `STATIC HISTORICAL` evidence is retained and must not be regenerated
for presentation. `DYNAMIC LIVE` evidence requires the readiness command or an
explicit MANUAL verification immediately before the walkthrough.

## Canonical evidence

| Evidence | Class | Exact source | What it proves | What it does not prove | Preferred browser surface | Fallback |
| --- | --- | --- | --- | --- | --- | --- |
| Current pipeline architecture | STATIC HISTORICAL | Buildkite Build #281 | Individually visible validation, `validation-complete`, CML/Batfish fan-out, sanitized annotations, immutable promotion, and the human authorization boundary | A new device write during the demo | Build #281 pipeline timeline and annotations | [Buildkite workflow](../architecture/buildkite-workflow.md) and repository pipeline tests |
| PR-only staging | STATIC HISTORICAL | Buildkite Build #280 | Disposable create → READ-ONLY validate → destroy and protected delivery ineligible on a PR | Application of the pending live plan or a live write | Build #280 staging job and annotation | [Staging operations](../architecture/buildkite-ephemeral-cml-staging-operations.md) |
| Ambiguous-write safety | STATIC HISTORICAL | Buildkite Build #259 | Write outcome uncertain → stop → never retry → independent reconciliation → actual state established | A successful write or permission to replay the attempt | Build #259 bounded deploy-gate history | [Recovery safety](../architecture/recovery-safety.md) and [browser catalog](browser-surfaces.md) |
| Protected Cisco success | STATIC HISTORICAL | Build #267; change `CHG-SNMP-11C3-CISCO-004`; audit `01a050b6-6d7d-4294-990a-0f82ed978409` | Separately authorized Cisco live SNMPv3 provisioning with durable success evidence | Persistent live SNMP polling | Build #267, then the durable viewer record | [Increment 11C acceptance](../acceptance/continuous-observability-increment-11c.md) |
| Protected Junos success | STATIC HISTORICAL | Build #275; change `CHG-SNMP-11C3-JUNOS-001`; audit `01a0513c-9d87-4faf-8108-9029c5f44c49` | Junos protected execution after disposable rehearsal, using vendor-aware safety and durable success evidence | Persistent live SNMP polling or a fleet deployment | Build #275, then the durable viewer record | [Increment 11C acceptance](../acceptance/continuous-observability-increment-11c.md) |
| Protected configuration chronology | STATIC HISTORICAL | Build #158; audit `01a04384-f1ea-47ee-b2be-a92192b207fc`; observation `0e56e7e0-87cd-4c04-864a-55c88f3c659f` | PRE/write/POST ordering, private chronology metadata, `TEMPORALLY_BRACKETED`, and explicit `NOT_PROVEN` causality | Proof that temporal bracketing establishes causation or access to raw configuration | Durable viewer exact record | [10C-7B acceptance](../acceptance/protected-configuration-observation-increment-10c7b.md) |
| Fail-closed authorization | STATIC HISTORICAL | Buildkite Build #273 | Failure stopped before credential read, NETCONF preflight, or device write; the historical build was not retried | A device or provider failure | Build #273 bounded logs/timeline | [Increment 11C acceptance](../acceptance/continuous-observability-increment-11c.md) |
| Correction lineage | STATIC HISTORICAL | GitHub PR #99 and PR #100 | Fresh source, commit, build, and authorization followed the failed attempt | Permission to amend or retry historical execution | GitHub PR history | Increment 11C acceptance narrative |
| Current live topology | DYNAMIC LIVE | CML `NCDP Live` | The accepted persistent two-router realization currently exists and both nodes are booted | Desired-state authority, staging ownership, or proof of a new write | CML topology and node-state UI | MANUAL verification prompted by `ncdp-demo-readiness` |
| Current observability | DYNAMIC LIVE | Grafana `NCDP Management Reachability` | Current pipeline-independent, read-only management reachability presentation | Autonomous remediation or persistent SNMP polling | Provisioned Grafana dashboard | Prometheus ready/targets/rules pages plus MANUAL target-health verification |
| Durable evidence viewer | DYNAMIC LIVE presentation of STATIC HISTORICAL authority | Foreground `ncdp-evidence-viewer` over the existing validated store | Browser-safe audit identity and metadata-only configuration correlation | A second evidence authority, raw artifact browser, or control plane | Viewer: #158 chronology; #267/#275 success; optional #263 `AMBIGUOUS` | Typed AuditStore readers and the acceptance documents above |

Build #259 remains the primary ambiguous-write narrative. Viewer record #263 is
an optional additional bounded `AMBIGUOUS` outcome example, not a replacement
for the independently reconciled #259 story.

Buildkite retention is not durable evidence authority. Buildkite explains the
pipeline attempt; AuditStore and ConfigurationObservationStore retain the typed,
digest-validated correlation, while Oxidized retains private actual-state
chronology. No screenshot is authoritative.

## Dynamic readiness ownership

- `ncdp-demo-readiness` automates local Git, Docker, loopback NetBox/Grafana/
  Prometheus/OpenBao availability, canonical typed evidence, and an already
  running viewer.
- The operator manually confirms authenticated NetBox, CML, and Buildkite
  sessions, both `NCDP Live` nodes `BOOTED`, and healthy Grafana target panels.
- A missing foreground viewer is `OPTIONAL`, not platform failure; start it with
  the supplied private AuditStore root before the browser walkthrough.
