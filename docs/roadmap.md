# Current roadmap

This roadmap records current capability and remaining work. Detailed attempt
history belongs in ADRs and acceptance records.

## Completed foundations

1. **Repository and executable foundation — complete.** Typed Python policy,
   immutable artifacts, tests, packaging, containers, and visible validation
   gates are accepted.
2. **Cisco and Junos interface-description verticals — complete.** Profiled
   schema-v2 planning/execution, exact approval binding, independent
   validation, honest ambiguity, Cisco targeted inverse, and Junos
   commit-confirmed/explicit confirmation are implemented and LIVE-accepted for
   C8000V IOS-XE and vJunos.
3. **NetBox and OpenBao — complete.** NetBox is the GET-only identity/source-of-
   truth boundary and OpenBao supplies bounded stable-device-ID credentials.
4. **Batfish assurance — complete for the profiled PR boundary.** The active
   step evaluates the exact four-device candidate without LIVE or credential
   authority.
5. **Audit and configuration history — complete for accepted scope.** Historical
   schema-v1 protected evidence remains parseable; current Oxidized chronology
   is exact-four and profile-derived.
6. **Management observability — complete.** Prometheus, Blackbox, Grafana,
   Alertmanager, and advisory rules consume the exact-four profiled population
   without remediation authority.

## Detour B — COMPLETE

The profiled migration is complete through controlled LIVE acceptance of the
local deploy boundary and the exact-two runtime deletion gate:

- the sole managed population contract is
  `ncdp-profiled-inventory` plus exact Git-owned identities 1/2/8/9;
- management observability and Oxidized consume all four through profiled
  read-only projections;
- SNMPv3 SHA256/AES128 observability is a capability projection currently
  selecting devices 1/2, not legacy exact-two admission;
- `profiled-plan` and `profiled-deploy` are the only current ordinary planning/
  write commands;
- interface-description write admission remains only C8000V IOS-XE and vJunos;
- IOSv and IOSvL2 are managed members but unsupported for that write operation;
- schema-v1 local/fleet execution, SNMP provisioning writes, protected delivery,
  disposable exact-two CML staging, and the Terraform/operator twin are retired;
- Buildkite retains validation and profiled four-device PR assurance with no
  device-write step; and
- the B5 D0/O/D1 seam and four generation-one records are unchanged.

Controlled external acceptance removed the obsolete `ncdp-managed` assignments
from devices 1/2 exactly once; the Tag object remains unassigned. The profiled
population stayed exactly active devices 1/2/8/9. A separately reviewed
Oxidized reconciliation refreshed its private source, loopback runtime, and
readiness to exact-four. Current code and retained runtime have zero legitimate
dependency on the legacy tag. B5 remained byte-identical and unchanged.
The former **external tag retirement pending** milestone is therefore complete.

## Profiled disposable staging — Phase 1 implemented

The replacement for retired exact-two staging is an exact-four profiled
Terraform realization: six nodes, nine links, 17 managed resources,
management-only Day-0, run-scoped strict trust, profile-derived readiness, and
read-only collection through `StagingRealizationContext` and
`ProfileReadOnlyAdapter`. Lifecycle hardening admits CML independently, fences
START and destroy with saved exact-action plans, cleans known partial state
without requiring a READY context, and retains verifier-only recovery inputs.
Static Terraform validation is current. Controlled
local create/validate/destroy acceptance and later PR-only Buildkite activation
remain pending. Protected delivery remains retired.

## Managed-state proposals

B4 routed underlay, OSPF, VLAN/trunk, and ACL remain read-only D1 proposals with
profiled observation and four-device Batfish assurance. They have no LIVE write
authority. B5 maintains four envelope-scoped generation-one `INITIAL_ADOPTION`
chains and distinguishes D0/O drift from D0/D1 proposed change. Interface
description is outside those envelopes and schema-v2 execution does not advance
D0.

## Continuous observability follow-up

- **SNMP 11C-1/11C-2 — complete:** standard-IETF module generation and synthetic
  SNMPv3 protocol validation are accepted.
- **SNMP 11C-3 — historical acceptance:** schema-v1 protected provisioning on
  devices 1/2 succeeded; that write path is now retired.
- **SNMP 11C-4 — deferred:** persistent exporter materialization and live
  UDP/161 polling are not claimed. The eligible target projection is already
  profiled and currently exact devices 1/2.
- **gNMI/OpenConfig 11D — deferred/skipped.**

## Remaining work

- Final demonstration rehearsal and repository closure.
- Any future profiled fleet rollout, protected delivery, disposable staging, or
  new write vertical requires separate architecture review and acceptance.
