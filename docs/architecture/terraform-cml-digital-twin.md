# Terraform and CML digital-twin architecture

## Scope

Increment 8 establishes reproducible personal-CML infrastructure lifecycle for
digital-twin testing. Under ADR 0014, staging is ephemeral integration
infrastructure: a run creates a fresh Terraform-owned CML lab, validates its
first-boot realizations, retains sanitized evidence, and destroys the complete
twin. Terraform is not a network-device configuration provider, inventory
system, credential store, or source of NCDP targeting identity.

Increment 8A established the discovery and architecture contract. Increment 8B
implements the exact Terraform/provider pins, data-source foundation, external
state boundary, static CI validation, and accepted read-only plan. Increment 8C
accepted initial creation plus the controlled `DEFINED_ON_CORE` to `STARTED`
to `STOPPED` lifecycle. Increment 8D proved Day-0 fresh-first-boot
manageability, whole-twin replacement, and complete destruction, while a
same-realization vJunos restart failed. ADR 0014 therefore supersedes the
persistent operational staging assumption; Increment 8E will implement the
ephemeral pipeline.

## Authority boundary

| Property | Authority |
| --- | --- |
| Terraform-owned lab and node existence | Terraform/CML |
| Node definition, image, CPU/RAM, canvas, links, connector, lifecycle | Terraform/CML |
| Stable device and interface identity, management IP, platform, role, targeting metadata | NetBox |
| Managed network configuration, automation and validation policy | Git/NCDP |
| Personal-lab minimum Day-0 manageability template | Git/Terraform/CML |
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

An equivalent twin consumes 6 vCPUs and 14,336 MiB RAM. Increment 8A measured
the then-current 10-node legacy lab and found that simultaneous operation of
both complete router sets would leave only approximately 1.1–1.5 GiB RAM
margin. Since that discovery, the operator has manually removed unrelated and
passive nodes from the legacy lab. The exact margin is therefore historical and
must not be used as current admission evidence or as proof that concurrent heavy
runtime is now safe. Before the first 8C `STARTED` transition, a fresh read-only
CML capacity check must fail closed unless sufficient capacity is demonstrated.
Initial `DEFINED_ON_CORE` creation remains distinct from that future operational
capacity decision.

### Increment 8C physical topology

The selected twin uses an explicit management fabric and two explicit
data-plane links. Every endpoint is bound by slot; no link uses next-free
interface selection.

| Link purpose | Endpoint A | Endpoint B |
| --- | --- | --- |
| Management | `system-bridge` port/slot 0 | `management-switch` port 0 |
| Management | `management-switch` port 1 | `core-02` slot 0 (`GigabitEthernet1`) |
| Management | `management-switch` port 2 | `edge-junos-01` slot 0 (`fxp0`) |
| Management | `management-switch` port 3 | `core-03` slot 0 (`GigabitEthernet1`) |
| Data plane | `core-02` slot 3 (`GigabitEthernet4`) | `edge-junos-01` slot 1 (`ge-0/0/0`) |
| Data plane | `edge-junos-01` slot 2 (`ge-0/0/1`) | `core-03` slot 2 (`GigabitEthernet3`) |

The reserved, deliberately unlinked change-target interfaces are
`core-02 GigabitEthernet2`, `core-02 GigabitEthernet3`,
`edge-junos-01 ge-0/0/2`, and `core-03 GigabitEthernet2`. CML tags stage
infrastructure before routers and do not provide NCDP target selection.

Canvas placement is deterministic: `system-bridge` at `(-400, -200)`,
`management-switch` at `(-150, -200)`, `core-02` at `(100, -400)`,
`edge-junos-01` at `(400, -200)`, and `core-03` at `(700, -400)`.

### Provider lifecycle state machine

The lifecycle input has no default. Missing operator intent fails closed because
provider `0.9.3-beta1` has no single state that is safe across every phase:

- Initial topology creation requires explicit `DEFINED_ON_CORE`. It creates the
  Terraform-owned lab, nodes, links, and lifecycle resource without booting the
  heavy routers, device bootstrap, or NCDP cutover.
- `STARTED` is an explicit operational start. Its first use requires separate
  review and authorization after controller capacity and the accepted legacy
  lab runtime are handled.
- `STOPPED` is an operational stop valid only after a successful `STARTED`
  state. The provider rejects `DEFINED_ON_CORE` to `STOPPED`.
- `DEFINED_ON_CORE` requested after operational use invokes reset/wipe
  semantics and is not routine stop behavior.

Terraform does not infer lifecycle intent from state, CML observations,
workspaces, time, or resource existence. Increment 8C-1 was plan-only and
established the explicit `DEFINED_ON_CORE` lifecycle contract. Increment 8C-3
created and accepted the Terraform-owned twin in `DEFINED_ON_CORE`; no node was
started or booted. Increment 8C-4 then admitted capacity by temporarily stopping
only the accepted legacy heavy routers, accepted the twin in `STARTED`, returned
it to operational `STOPPED`, and restored the legacy routers. Every lifecycle
plan and apply changed only `cml2_lifecycle.twin`, and router stored
configuration remained empty. See the
[Increment 8C lifecycle acceptance report](../acceptance/terraform-cml-lifecycle-increment-8c.md).
A later `DEFINED_ON_CORE` transition remains reset/wipe semantics. ADR 0014
changes the normal staging contract to fresh create and complete destroy rather
than persistent realization reuse. Reboot/restart is now an explicit scenario
test, not general staging readiness.

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
hard-coded. Terraform's local backend stores state and backup files as plaintext
and does not itself provide encryption. It is acceptable initially for the
single-operator personal lab only if those files have restrictive OS
permissions and the underlying host or storage encryption is independently
verified. If independently encrypted local storage cannot be established, an
encrypted remote backend must be selected before live state is created. Saved
plans with sensitive inputs are avoided unless a later explicit contract
protects and requires them.

Provider access uses only these ephemeral environment inputs:

- `CML2_ADDRESS`
- `CML2_TOKEN`
- `CML2_CACERT`

The JWT never enters HCL, `.tfvars`, state, outputs, Git, logs, artifacts, or
Buildkite metadata. TLS verification is required. Neither `skip_verify = true`
nor `CML2_SKIP_VERIFY=true` is permitted. Because the controller certificate is
self-signed, the operator must supply PEM-encoded trusted CA or controller
certificate content for that exact controller through `CML2_CACERT`, according
to the provider contract, before 8B performs live read-only provider access.
`CML2_CACERT` is not assumed to be a filesystem path. Private key material is
not committed.

## Personal-lab Day-0 bootstrap and cutover

ADR 0013 supersedes only ADR 0012's credential-bearing Day-0 prohibition for
this personal CML digital twin. Terraform/CML may materialize the minimum
initialization needed to make a lab router manageable: hostname realization,
management interface/address, local lab account, SSH, NETCONF, and required
platform prerequisites. This remains infrastructure initialization and cannot
include NCDP-managed intent such as interface descriptions or routing.

The authority flow is:

```text
NetBox identity, management IP, and platform
          +
OpenBao device credentials
          +
Git-reviewed minimum Day-0 template
          |
          v
bounded Terraform runtime inputs
          |
          v
external Terraform state + cml2_node.configuration
          |
          v
CML stored Day-0 configuration
```

NetBox remains authoritative for the values and stable identity; OpenBao
remains credential authority. Required inputs have no credential defaults or
committed tfvars. The rendered configuration is sensitive in normal Terraform
display, but its credential copy deliberately persists in external Terraform
state and CML Day-0 storage. State stays outside Git with restrictive
permissions on encrypted host storage. Saved plans containing the bootstrap are
prohibited. This tradeoff is accepted only for the personal lab and is not a
production secret-distribution design.

The selected mechanism is `cml2_node.core_02.configuration`, not lifecycle
`configs` or named configurations. Provider `0.9.3-beta1` documents node
configuration as Day-0 and requires replacement when it changes after the node
has started. The existing `${node.id}:${node.generation}` update trigger then
reconciles lifecycle for the replacement. Lifecycle config injection requires
a `DEFINED_ON_CORE` node and is outside this pattern.

Increment 8D-1 accepted the CML browser console as the initial one-time manual
IOS XE feasibility channel. Increment 8D-2 then accepted persistent manual
manageability, unchanged NetBox/OpenBao identity, strict SSH trust, read-only
NCDP planning, and restart persistence while the stored/state configuration
remained empty. Those historical proofs remain valid, but ADR 0013 changes the
future IOS XE recreation architecture.

The [Increment 8D-1 console feasibility acceptance](../acceptance/terraform-cml-console-bootstrap-feasibility-increment-8d.md)
proved those properties for a non-secret IOS XE runtime hostname. CML stored
configuration stayed zero length, Terraform refresh did not import active
running configuration, and the unsaved marker disappeared after restart. This
does not by itself accept management-IP or authentication bootstrap, SSH or
NETCONF, Junos bootstrap, reset/recreate, or NCDP cutover.

Increment 8D-2 accepted the next IOS XE boundary. The legacy lab is deliberately
kept stopped to remove its duplicate management identity, and `192.168.4.14`
now realizes the unchanged NetBox identity on Terraform-created `core-02`.
One-time manual console bootstrap persists management, the unchanged OpenBao
credential authenticates over strict SSH host trust, and the existing NCDP path
reaches read-only planning. Saved device configuration remains on the router
disk and outside CML stored configuration and Terraform state. See the
[Increment 8D-2 acceptance report](../acceptance/terraform-cml-iosxe-management-bootstrap-increment-8d.md).

Increment 8D-2B replaces manual IOS XE bootstrap with the ADR 0013 Day-0
exception. Controlled replacement automatically produced first-boot and restart
manageability with zero console configuration while the stable NetBox identity
and OpenBao credential remained unchanged. Strict SSH, TCP/830, and existing
NCDP read-only planning/preflight succeeded. See the
[Increment 8D-2B acceptance report](../acceptance/terraform-cml-iosxe-day0-bootstrap-increment-8d.md).

Replacing a previously started node also recreates links that reference its CML
UUID. The recreated core-02 to edge-junos link initially remained
`DEFINED_ON_CORE` because CML would not start it while endpoint interfaces were
down. Temporarily running exactly its two endpoint routers allowed the link to
transition `STARTED` to `STOPPED`; no Junos configuration was involved. This is
an operational-state normalization detail, not an NCDP configuration
dependency.

The accepted legacy lab remains deliberately STOPPED to prevent duplicate
ownership of stable NetBox-managed endpoints. It has not been deleted or
retired. The final Increment 8D Terraform twin was completely destroyed, so no
Terraform realization currently owns `core-02` or `edge-junos-01`. Future
ephemeral runs must freshly verify NetBox identity, OpenBao provenance, SSH host
trust, platform, hostname, and topology before NCDP validation.

## Increment contracts

### 8A — discovery and architecture contract

Authenticated read-only discovery, capacity analysis, tool selection, authority,
state, TLS/authentication, bootstrap, and separate-twin decisions. Complete when
the documentation and ADR are reviewed and merged.

### 8B — Terraform foundation and plan-only contract

Implemented and accepted after merge: Terraform `1.15.8`, provider
`0.9.3-beta1`, and the multi-platform dependency lock are exact. The
`infrastructure/cml` root resolves controller metadata, the unique `System
Bridge`, and accepted router images through data sources only. CI validates the
root without credentials, backend, or CML access. The live acceptance was an
unsaved speculative plan with external state configuration, verified TLS, zero
managed-resource actions, no persistent state, and no CML mutation. See the
[Increment 8B acceptance report](../acceptance/terraform-cml-foundation-increment-8b.md).

### 8C — Terraform-owned topology and lifecycle acceptance

Complete. The separate deterministic topology was created with explicit
`DEFINED_ON_CORE`. Fresh capacity admission preceded the accepted operational
`STARTED` transition, and the twin was then accepted in steady `STOPPED` state
before the legacy runtime was restored. A later `DEFINED_ON_CORE` request has
reset/wipe semantics. See the
[lifecycle acceptance report](../acceptance/terraform-cml-lifecycle-increment-8c.md).

### 8D — Day-0 investigation and lifecycle decision

Complete. IOS XE and vJunos both achieved automatic, zero-console management on
fresh first boot using NetBox/OpenBao authority and ADR 0013 Day-0 renders. An
explicit whole-twin replacement recreated all 13 managed resources and
converged cleanly. The same vJunos UUID then failed to restore ARP, ICMP, SSH,
or NETCONF after restart, so the persistent 8D-3 acceptance contract did not
pass. ADR 0014 adopts fresh ephemeral staging instead. The final Terraform twin
was destroyed completely and its managed state is empty. See the
[Increment 8D investigation report](../acceptance/terraform-cml-vjunos-day0-bootstrap-increment-8d.md).

### 8E — ephemeral CML staging pipeline

Next. Design a reusable Terraform root/module, build-scoped state and run
identity, serialized fixed-address staging concurrency, create and first-boot
readiness, NCDP staging validation, sanitized evidence, finally-style destroy,
cleanup verification, and failed-destroy state retention. Buildkite integration
belongs to this increment and is not implemented by 8D.
