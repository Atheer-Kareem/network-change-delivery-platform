# Terraform and CML digital-twin architecture

## Scope

Increment 8 establishes reproducible personal-CML infrastructure lifecycle for
digital-twin testing. Terraform controls only a separately created CML lab and
its infrastructure realization. It is not a network-device configuration
provider, inventory system, credential store, or source of NCDP targeting
identity.

Increment 8A is documentation and architecture only. Terraform installation and
plan-only foundations begin in 8B; CML creation and lifecycle acceptance begin
in 8C; state-free bootstrap, reset/recreate, and NCDP cutover compatibility are
8D.

## Authority boundary

| Property | Authority |
| --- | --- |
| Terraform-owned lab and node existence | Terraform/CML |
| Node definition, image, CPU/RAM, canvas, links, connector, lifecycle | Terraform/CML |
| Stable device and interface identity, management IP, platform, role, targeting metadata | NetBox |
| Managed network configuration, automation and validation policy | Git/NCDP |
| Explicit future non-secret bootstrap policy and templates | Git/NCDP |
| Device credentials | OpenBao |
| Runtime CML and device observations | Evidence only |

CML UUIDs identify CML realization objects; they are not stable NCDP inventory
identity. Terraform tags organize its infrastructure but cannot select NCDP
deployment targets. Before cutover, NCDP must validate Terraform node/image
realization against NetBox-authoritative platform identity.

## Selected toolchain

The implementation contract is Terraform CLI `1.15.8` with exactly
`CiscoDevNet/cml2` `0.9.3-beta1`. The first implementation must pin both
contracts and commit the generated `.terraform.lock.hcl`. It must not use a
floating provider constraint, Terraform RC/beta/alpha builds, OpenTofu, or CML2
provider `0.9.1`.

CML `2.10.0+build.13` satisfies the provider's CML 2.9-or-newer requirement.
Although the provider is beta, its node generation, lifecycle update triggers,
add/replace reconciliation, link drift reconciliation, and connector
device-name handling are required for the narrow personal-lab lifecycle and
reset contract.

## Separate-twin topology

Terraform creates a new lab rather than importing the accepted running lab. The
new lab may coexist in CML while stopped, preserving the externally accepted
Increment 7 environment and proving reset/recreate only on objects Terraform
created.

The accepted live CML nodes `cat8000v-0`, `vjunos-router-0`, and `cat8000v-1`
currently connect only through the shared management fabric. They have no CML
data-plane links and therefore are not an exact data-plane twin.

The sanitized Batfish assurance scenario models:

```text
core-02 GigabitEthernet1 -- edge-junos-01 ge-0/0/0
edge-junos-01 ge-0/0/1 -- core-03 GigabitEthernet1
```

That model is synthetic behavioral-assurance input, not observed CML wiring. In
the live CML lab, Cisco `GigabitEthernet1` is the management interface.
Terraform must not translate those sanitized interface names into CML links.
Every future CML data-plane scenario must explicitly select non-management
interfaces and define its own topology contract. Management interfaces remain
protected.

An equivalent twin consumes 6 vCPUs and 14,336 MiB RAM. Available controller
capacity permits it, but simultaneous operation of both complete router sets
leaves only approximately 1.1–1.5 GiB RAM margin. Coexistence therefore means
separate ownership, not simultaneous heavy runtime: lifecycle/reset acceptance
keeps only one three-router set running unless later capacity evidence approves
otherwise.

## External connector

`System Bridge` is a CML UI label, not a Linux device name. The inspected node
and interface representations did not expose its backing name. Increment 8B
must use the provider's `cml2_connector` data source, uniquely match the
`System Bridge` label, and consume the returned `device_name`. Connector objects
also expose `id`, `protected`, `snooped`, and `tags`. Zero or multiple label
matches are ambiguous and must stop planning. Values such as `bridge0` or
`virbr0` must never be guessed.

## State and authentication security

Terraform state is sensitive operational data even when no device credential is
intentionally present. Live local state stays outside the repository under an
operator-configurable location or backend. The repository ignores `.terraform/`,
`*.tfstate`, and `*.tfstate.*`; no user-specific absolute state path is
hard-coded. An encrypted and access-controlled local backend is acceptable for
the single-operator personal lab. Saved plans with sensitive inputs are avoided
unless a later explicit contract protects and requires them.

Provider access uses only these ephemeral environment inputs:

- `CML2_ADDRESS`
- `CML2_TOKEN`
- `CML2_CACERT`

The JWT never enters HCL, `.tfvars`, state, outputs, Git, logs, artifacts, or
Buildkite metadata. TLS verification is required. Neither `skip_verify = true`
nor `CML2_SKIP_VERIFY=true` is permitted. Because the controller certificate is
self-signed, the operator must establish a trusted PEM for that exact controller
and pass it with `CML2_CACERT` before 8B performs live read-only provider access.
Private key material is not committed.

## State-free bootstrap and cutover

Credential-bearing startup configuration cannot pass through Terraform node,
lifecycle, or topology configuration fields because the payload can persist in
state even when marked sensitive. Existing stored CML configurations are also
unsuitable as an adoption source: their hostnames are placeholders, they are not
authoritative runtime identity, and a negative secret-pattern scan cannot prove
arbitrary configuration non-sensitive.

Increment 8D must introduce a separate state-free boundary:

```text
NetBox identity, management IP, and platform
          +
OpenBao device credentials
          +
Git/NCDP non-secret bootstrap policy
          |
          v
Python/operator in-memory rendering
          |
          v
direct write to Terraform-owned CML node
          |
          v
discard credentials and rendered payload
```

Terraform retains lifecycle ownership but never owns the secret-bearing payload.
The accepted legacy lab remains active until it cannot conflict with stable
NetBox-owned management endpoints. After state-free bootstrap and Terraform
startup, NCDP freshly verifies NetBox identity, OpenBao provenance, SSH host
trust, platform, hostname, and topology. Only successful acceptance permits the
legacy lab to be retired separately.

## Increment contracts

### 8A — discovery and architecture contract

Authenticated read-only discovery, capacity analysis, tool selection, authority,
state, TLS/authentication, bootstrap, and separate-twin decisions. Complete when
the documentation and ADR are reviewed and merged.

### 8B — Terraform foundation and plan-only contract

Install and pin Terraform `1.15.8`; pin provider `0.9.3-beta1`; commit the lock
file; create the `infrastructure/cml` root/module structure; enforce environment,
connector, state, formatting, validation, and static policy contracts; and run
only safe read-only provider/data-source planning. It performs no CML resource
mutation.

### 8C — Terraform-owned topology and lifecycle acceptance

Create the separate lab, deterministic nodes and links, prefer a stopped default
state, and accept start/stop behavior without NCDP cutover or a requirement to
run both heavy labs simultaneously.

### 8D — reset/recreate and NCDP compatibility

Implement state-free bootstrap, controlled management cutover, destroy/recreate
and reset acceptance, deterministic lifecycle reconciliation, explicit safe SSH
host-trust re-establishment, and fresh NetBox/OpenBao/NCDP compatibility checks.
Prove that Terraform controls CML lifecycle only, never production configuration.
