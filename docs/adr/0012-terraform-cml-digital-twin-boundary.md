# ADR 0012: Terraform-owned CML digital-twin boundary

## Status

Accepted for Increment 8 implementation after Increment 8A merge.

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

Increment 8D must identify and prove a runtime bootstrap channel that does not
populate provider-readable CML stored configuration. CML console or serial
interaction with a booted device is a candidate, but is neither selected nor
accepted until feasibility is demonstrated. Acceptance must prove that
credentials and rendered secret material are absent from CML stored
configuration and Terraform plans/state, and that a Terraform refresh after
bootstrap cannot recover secret-bearing data into state. If no such boundary is
proven, 8D stops and revisits the architecture rather than weakening state
secrecy. Increment 8A does not implement this boundary.

## Consequences

The accepted Increment 7 lab remains the active NCDP environment until a
controlled cutover. A running twin cannot reuse its stable management addresses.
Before activation, the legacy lab must be unable to conflict; state-free
bootstrap then applies NetBox/OpenBao-backed management settings, Terraform
starts the twin, and NCDP independently verifies inventory identity, credential
provenance, SSH host trust, platform, hostname, and expected topology. Retirement
of the legacy lab is a later, separate operation.

Reset/recreate is proven on infrastructure Terraform owns from birth, beta
provider risk stays bounded, CML UUIDs remain realization identifiers rather
than NCDP inventory identities, and rollback remains clear while the accepted
legacy lab exists. No Terraform implementation, CML change, or cutover is part
of Increment 8A.
