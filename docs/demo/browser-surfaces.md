# Browser demonstration surfaces

This catalog records the small, safe set of native browser surfaces selected by
the Increment 12D audit. It is a navigation and disclosure guide, not the final
demonstration script. All local services remain personal-lab surfaces; only the
public GitHub material is suitable for an unauthenticated portfolio visitor.

## Primary surfaces

| Surface | What it proves | Safe page or view | Do not click or show |
| --- | --- | --- | --- |
| GitHub README | Public architecture, scope, safety model, and implemented capability | Repository README and its linked flagship architecture | Private local paths, unrelated account settings, or unpublished operational notes |
| Buildkite Build #281 | Current visible validation, CML/Batfish fan-out, immutable promotion, approval, and deploy-gate architecture | Pipeline timeline, step labels, and sanitized annotations | Environment tabs, raw artifact wandering, or token/agent configuration |
| NetBox | Authoritative two-device infrastructure, platform, interface, and IP identity | Managed-device list, then the `core-02` and `edge-junos-01` device/interface pages | Admin, token, configuration-context, secrets, or credential-reference views |
| CML `NCDP Live` | The distinct persistent, manually owned two-router live topology | Lab topology canvas and node-state summary | Consoles, Day-0 configuration, API credentials, node definitions, or edit controls |
| Grafana `NCDP Management Reachability` | Pipeline-independent, read-only management-service visibility | Provisioned dashboard at `http://127.0.0.1:3000` | Datasource settings, user/admin pages, or unrelated dashboards |
| Buildkite Build #275 | Accepted Junos protected write with fresh validation and vendor-specific safety | Build timeline, approval boundary, deploy-gate result, and bounded logs/metadata | Raw artifacts or unrelated environment data |
| NCDP durable evidence viewer | Digest-validated audit identity plus metadata-only Oxidized correlation | Index and exact record detail on `http://127.0.0.1:8765` | The private store itself; no raw/download route exists |

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
| Buildkite Build #280 | PR-only disposable staging presentation | Staging create → READ-ONLY validate → destroy step and sanitized annotation | CML credentials, artifacts, or raw provider output |
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
