# Browser demonstration surfaces

This catalog records the small, safe set of native browser surfaces selected by
the original Increment 12D audit, reconciled with current profiled delivery.
Start with the [current acceptance](../acceptance/profiled-main-delivery.md) and
[three-outcome evidence guide](evidence-package.md); no fresh live write is needed. All
local services remain personal-lab surfaces; only the
public GitHub material is suitable for an unauthenticated portfolio visitor.

## Primary surfaces

| Surface | What it proves | Safe page or view | Do not click or show |
| --- | --- | --- | --- |
| GitHub README | Public architecture, scope, safety model, and implemented capability | Repository README and its linked flagship architecture | Private local paths, unrelated account settings, or unpublished operational notes |
| Current delivery acceptance | User-supplied successful and blocked schema-v2 outcomes, exact supplied digests and explicit limits | [Canonical current record](../acceptance/profiled-main-delivery.md); no build number was supplied | Invented current build links or unsupplied logs/identities |
| NetBox | Authoritative managed device, platform, interface and IP identity | Managed-device list, then the selected delivery target; current members are core-02, edge-junos-01, transit-ios-01 and access-sw-01 | Admin, token, configuration-context, secrets, or credential-reference views |
| CML `NCDP Live` | The distinct persistent, operator-owned current proof population | Lab topology canvas and node-state summary | Consoles, Day-0 configuration, API credentials, node definitions, or edit controls |
| Grafana `NCDP Management Reachability` | Pipeline-independent, read-only management-service visibility | Provisioned dashboard at `http://127.0.0.1:3000` | Datasource settings, user/admin pages, or unrelated dashboards |
| Buildkite Build #275 | Historical accepted Junos protected write with fresh validation and vendor-specific safety | Build timeline, approval boundary, deploy-gate result, and bounded logs/metadata | Raw artifacts or unrelated environment data |
| NCDP durable evidence viewer | Historical audit/chronology and current profiled durable envelopes; COMPLIANT durability accepted; current chronology implemented offline | Index and exact record detail on `http://127.0.0.1:8765` | The private store itself; no raw/download route exists |

Current profiled details use `/profiled-records/<uuid>`; historical URLs remain
`/records/<uuid>`. The index distinguishes both families and sorts them by time.
Profiled COMPLIANCE has no human write authorization and requires no chronology.
Current EXECUTION chronology is implemented offline (see below). Current Buildkite delivery now publishes profiled envelopes through
its deploy boundary; publication requires protected operator store configuration.
Implementation tests use synthetic temporary stores. No new runtime acceptance is
claimed, and earlier accepted builds are not retroactively persisted. Do not
present an offline fixture as live delivery acceptance. See the
[durable foundation contract](../architecture/audit-and-configuration-history.md#current-profiled-durable-foundation).

Start the evidence viewer only when needed, in the foreground:

```console
uv run ncdp-evidence-viewer --audit-root <existing-private-audit-root>
```

It binds only to loopback, opens the existing store without creating paths, and
stops with Ctrl-C. It does not call GitHub, Buildkite, NetBox, CML, OpenBao,
Oxidized, or devices. Links to GitHub and Buildkite are constructed from fixed
reviewed bases and typed record identifiers; they are ordinary browser links,
not API calls.

## Supporting surfaces

| Surface | What it proves | Safe page or view | Do not click or show |
| --- | --- | --- | --- |
| Buildkite Build #281 | Historical validation/promotion/JWT-era pipeline | Selected historical timeline | Presenting it as the current pipeline |
| Buildkite Build #280 | Historical PR-only disposable staging presentation | Staging create → READ-ONLY validate → destroy step and sanitized annotation | CML credentials, artifacts, or raw provider output |
| Buildkite Build #259 | Ambiguous-write stop and independent-reconciliation story | Failed deploy-gate outcome and bounded safety narrative | Retry controls; this historical attempt must never be replayed |
| Buildkite Build #267 | Accepted Cisco SNMPv3 provisioning | Protected timeline and final bounded result | Credential material or device configuration |
| Buildkite Build #273 | Fail-closed Junos JWT authorization attempt | Failure before credential read, NETCONF preflight, or device write | Retry controls, OpenBao internals, or environment data |
| GitHub PR #99 and PR #100 | Fresh correction lineage after the non-retried failure | Reviewed commits, discussion, and merge history | Repository/account administration |
| Prometheus | Underlying target admission, rules, and alert evaluation | `http://127.0.0.1:9090/targets`, `/rules`, and `/alerts` | Status/configuration pages or raw service-discovery material |

Prometheus is supporting evidence because Grafana communicates the operational
story more quickly. Personal-lab addresses may appear in NetBox, CML, and
Prometheus; they are not credentials, but should be shown only when they clarify
identity or reachability.

## Avoid in the main walkthrough

| Surface | Decision | Reason |
| --- | --- | --- |
| OpenBao UI/API | Avoid in the primary walkthrough | The loopback-only native UI is an authenticated operator convenience, not part of the normal NCDP machine path. It is unnecessary for the 10–15 minute demonstration; never display secret values, tokens, auth configuration, or administrative internals. |
| Oxidized web | Avoid | Native revision/configuration navigation can expose raw device configuration. The evidence viewer presents only validated chronology metadata and explicit `NOT_PROVEN` causality. |
| Alertmanager and demo receiver | Avoid as separate stops | They add little beyond Grafana and Prometheus in a short walkthrough. |
| Raw Buildkite artifacts/log wandering | Avoid | Sanitized annotations and selected bounded logs tell the intended story without accidental disclosure or implementation noise. |
| CML console or Day-0 | Do not display | These are bootstrap/configuration surfaces, not evidence surfaces. |
| Terraform state | Do not display | It is private implementation state and unnecessary for the architecture claim. |
| Raw AuditStore/observation JSON | Do not display | The typed viewer intentionally omits locators, credentials, configuration paths, and raw payloads. |

The catalog does not create a new control plane: navigation never authorizes a
deployment, collection, recovery, or reconciliation action.

## Current profiled chronology boundary

Current EXECUTION detail shows PRE/POST statuses, commit/blob IDs, collected
timestamps, relationship and NOT_PROVEN causality, or NOT ESTABLISHED when no
child exists. COMPLIANCE shows NOT REQUIRED — COMPLIANT and does not access
chronology. Historical routes remain unchanged. No raw configuration, credential
reference or private filesystem path is displayed.

CAP-CONFIG-CHRONOLOGY is implemented offline and remains IN PROGRESS pending
acceptance. See the [current chronology contract](../architecture/audit-and-configuration-history.md#current-profiled-configuration-chronology).
