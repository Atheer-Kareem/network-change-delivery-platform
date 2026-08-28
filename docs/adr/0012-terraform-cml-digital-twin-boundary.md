# ADR 0012: Terraform-owned CML digital-twin boundary

## Status

Accepted for Increment 8 implementation after Increment 8A merge. ADR 0013
supersedes only this ADR's prohibition on credential-bearing Terraform/CML
Day-0 configuration inside the personal CML digital twin; the historical
rationale and all other authority boundaries remain accepted. ADR 0014
supersedes the persistent operational staging-lifecycle assumption: normal CML
staging now creates, validates, and destroys a fresh twin per run.

## Context

Increment 7 completed protected, commit-bound deployment to the accepted manual
personal-CML environment. Increment 8 must add reproducible CML infrastructure
lifecycle without placing production configuration, device credentials, or
stable inventory identity under Terraform authority. The accepted lab must
remain available while a beta CML provider proves lifecycle and reset behavior
on infrastructure it owns from creation.

Read-only Increment 8A discovery found CML `2.10.0+build.13`, a licensed and
healthy CML Personal controller, and sufficient capacity for a second equivalent
three-router topology. Running both complete router sets simultaneously would
leave only approximately 1.1–1.5 GiB RAM margin, so coexistence does not imply a
requirement to keep both heavy sets running.

## Decision

Increment 8 uses Terraform CLI `1.15.8` and exactly
`CiscoDevNet/cml2` `0.9.3-beta1`. The provider version is pinned exactly, not
with a floating `~>` constraint. OpenTofu, Terraform prereleases, and provider
`0.9.1` are not selected.

The provider remains beta. That risk is accepted only inside the personal-CML
digital-twin boundary because `0.9.3-beta1` supplies the lifecycle behavior
needed for reset/recreate acceptance: deterministic `cml2_node.generation`,
`cml2_lifecycle.update_triggers`, node add/replace reconciliation, link
lifecycle and drift reconciliation, and external-connector configuration by
actual Linux device name. It must never expand into production device
configuration.

The adoption strategy is a **separate Terraform-owned twin**. Terraform will
not import or adopt the accepted running lab. The twin may coexist in CML in a
stopped state. Full lifecycle acceptance keeps only one heavy three-router set
running at a time unless later capacity evidence changes that rule.

Terraform/CML owns only its lab, nodes, node/image realization, CML resource
sizing, canvas placement, links, external-connector attachment, lifecycle state,
and reset/recreate semantics. NetBox owns stable NCDP device and interface
identity, management addresses, platform, role, and targeting metadata.
Git/NCDP owns managed network-configuration intent and automation,
validation, assurance, and explicitly defined non-secret bootstrap policy.
OpenBao owns device credentials. Observed CML and device state is evidence, not
authority. CML node tags must not become a second NCDP targeting authority, and
node/image realization must be checked against NetBox platform identity before
cutover.

Terraform state is sensitive operational data and must not be committed.
Increment 8B will commit `.terraform.lock.hcl`, ignore `.terraform/`,
`*.tfstate`, and `*.tfstate.*`, keep live local state outside the repository,
and use an operator-configurable path or backend rather than a user-specific
absolute path. Terraform's local backend writes plaintext state and backup files;
it does not provide state-at-rest encryption. It is acceptable initially for
this single-operator lab only when those files have restrictive OS permissions
and the underlying host or storage encryption is independently verified. If
independently encrypted local storage cannot be established, an encrypted remote
backend is required before live state is created. Saved plans containing
sensitive inputs are prohibited unless explicitly protected and required.

Provider authentication uses ephemeral `CML2_ADDRESS`, `CML2_TOKEN`, and
`CML2_CACERT` environment inputs. The JWT must not enter Terraform source,
variable files, state, outputs, Git, saved logs, or Buildkite metadata. TLS
verification is mandatory; `skip_verify = true` and
`CML2_SKIP_VERIFY=true` are prohibited. Before live Terraform access, the
operator must supply PEM-encoded trusted CA or controller certificate content
for the exact self-signed controller through `CML2_CACERT`, according to the
provider contract. `CML2_CACERT` is not assumed to be a filesystem path.
Private key material is never committed.

The connector must be selected with the `cml2_connector` data source by the
unique label `System Bridge`, then configured using its returned
`device_name`. Zero or multiple matches fail closed. No Linux connector name is
guessed or hard-coded.

Terraform must not manage credential-bearing device startup configuration
through `cml2_node.configuration`, `cml2_node.configurations`,
`cml2_lifecycle.configs`, `cml2_lifecycle.named_configs`, topology-embedded
configuration, or an equivalent out-of-band CML API write to the same stored or
day-zero configuration fields. Terraform sensitivity markings do not keep
values out of state, and merely omitting these attributes from HCL is
insufficient: provider `Read()` refreshes the CML node and its Optional +
Computed `configuration` and `configurations` values can be persisted into
Terraform state.

This prohibition was the accepted boundary through Increment 8D-2. ADR 0013
supersedes it only for minimum manageability bootstrap in the personal CML
digital twin. It remains the boundary for production and for NCDP-managed
network intent.

Through Increment 8D-2, the accepted strategy required a state-free runtime
bootstrap channel that did not populate provider-readable CML stored
configuration or Terraform state. Increment 8D-1 proved console feasibility,
and Increment 8D-2 proved the resulting manual management bootstrap and state
boundary. ADR 0013 supersedes that requirement for future personal-twin
recreation: current personal-twin recreation uses credential-bearing
CML/Terraform Day-0 configuration. Production use and NCDP-managed network
intent remain outside that exception.

## Consequences

The accepted legacy lab remains deliberately STOPPED so it cannot conflict with
stable management addresses. Personal-twin recreation uses the Day-0 boundary
defined by ADR 0013, while NCDP continues to independently verify inventory
identity, credential provenance, SSH host trust, platform, hostname, and
expected topology. ADR 0014 makes those Terraform realizations ephemeral; no
persistent Terraform twin currently owns a stable NetBox identity.

Reset/recreate is proven on infrastructure Terraform owns from birth, beta
provider risk stays bounded, CML UUIDs remain realization identifiers rather
than NCDP inventory identities, and rollback remains clear while the accepted
legacy lab exists. No Terraform implementation, CML change, or cutover is part
of Increment 8A.
