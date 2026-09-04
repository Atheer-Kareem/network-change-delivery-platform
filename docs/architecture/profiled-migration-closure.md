# Profiled migration closure

This document records the final Detour-B source deletion gate. The code state is
one profiled exact-four managed architecture; external removal of the obsolete
`ncdp-managed` tags from NetBox devices 1/2 remains a separate controlled
acceptance action.

## Final authority

The managed population is exactly `netbox:dcim.device:1`, `:2`, `:8`, and `:9`
through `ncdp-profiled-inventory` plus `PROFILED_POPULATION_CATALOG`.
Membership grants no operation. Retained consumers project explicit
profile/capability authority:

| Consumer | Population or projection | Authority |
|---|---|---|
| `profiled-plan` | exact target within exact-four | read-only planning |
| `profiled-deploy` | C8000V IOS-XE or vJunos plus `interface_description` | local exact-digest write |
| Management observability | exact-four | credential-free read-only probes |
| Oxidized | exact-four profile-derived SSH/22 | read-only configuration chronology |
| SNMP observability | SHA256/AES128 profiles, currently devices 1/2 | telemetry only |
| Profiled LIVE verifier | exact-four | read-only identity/trust/readiness proof |
| B5 observation | exact-four envelope subjects | read-only D0/O/D1 comparison |
| PR Batfish | exact-four offline model | credential-free prevention evidence |

IOSv and IOSvL2 do not admit interface-description writes. Routed underlay,
OSPF, VLAN/trunk, ACL, SNMP provisioning, fleet rollout, and protected delivery
gain no write authority here.

## Runtime audit matrix

The audit classified repository occurrences by authority rather than deleting
names merely for aesthetics.

| Classification | Occurrences and disposition |
|---|---|
| `CURRENT_RUNTIME_MIGRATE` | Profiled LIVE verifier: removed its legacy exact-two resolver/assertion. CLI: retained only schema-v2 profiled planning/deployment. Pipeline: retained exact-four PR assurance and profiled passive-service validation. Observability, Oxidized, SNMP projection, and B5 were already profiled. |
| `CURRENT_RUNTIME_RETIRE` | Removed legacy `plan`, `deploy`, `fleet-plan`, `fleet-deploy`, `snmp-provisioning-plan`, and `deploy-buildkite-promotion`; protected gate/promotion/legacy assurance scripts; disposable staging wrapper/hook/driver/recovery/annotation; staging and protected OpenBao operator entry scripts; exact-two Oxidized operator twin; Terraform CML root/module/ephemeral source; Terraform pipeline validation; and commented staging/protected pipeline blocks. |
| `HISTORICAL_COMPATIBILITY` | Schema-v1 `DeploymentPlan`, `FleetDeploymentPlan`, `ChangeRecord`, `FleetChangeRecord`, inventory/workflow/fleet/vendor models, promotion/request/audit models, staging evidence types, and SNMP provisioning evidence remain importable for historical parsing, audit, and deterministic contract tests. No current entry point invokes their executors. |
| `HISTORICAL_DOCUMENTATION` | Existing ADRs and acceptance records remain byte-for-byte historical evidence. Architecture pages describing retired systems are explicitly marked historical rather than rewritten as if those systems were current. |
| `TEST_ONLY` | Legacy provider/executor unit tests retain compatibility and safety coverage; deterministic schema-v1 fixtures remain test-only. Closure tests fence current CLI, pipeline, population, projections, unsupported profiles, and B5 isolation. |

## Retirement decisions

The old protected schema-v1 delivery was successfully engineered and accepted,
but rebuilding it around the profiled architecture is outside this closure. Its
privileged current entry points are removed. A future protected design must be
new, schema-v2/profile-aware, and separately reviewed.

The disposable exact-two CML staging runtime and Terraform/operator twin are
also retired, not paused. They are not extended to exact-four because the
accepted current realization is the persistent operator-owned exact-four `NCDP
Live` lab. No running CML object is changed by source retirement.

## Deletion gate

- No current CLI imports or constructs `NetBoxInventoryProvider` or
  `MultiVendorAdapter`.
- No current CLI, privileged script, or pipeline step invokes `plan_change`,
  `deploy_plan`, `plan_fleet`, or `deploy_fleet`.
- No Buildkite device-write, protected-delivery, or CML-staging path remains.
- No retained current runtime consumer queries `ncdp-managed`.
- SNMP targets derive from the exact-four profile catalog and capability.
- `ProfiledDeploymentPlan`/`ProfiledChangeRecord` execution and its accepted
  operation matrix are unchanged.
- Profiled execution has no managed-state store dependency and cannot advance
  D0 for interface descriptions.

External legacy-tag retirement is deliberately absent from this source pass.
After review, the operator may remove only the obsolete tags and record a new
secret-free acceptance result. Until then those tags are inert external markers,
not runtime authority.
