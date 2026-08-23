# Terraform and CML digital-twin architecture

## Scope

Increment 8 establishes reproducible personal-CML infrastructure lifecycle for
digital-twin testing. Terraform controls only a separately created CML lab and
its infrastructure realization. It is not a network-device configuration
provider, inventory system, credential store, or source of NCDP targeting
identity.

Increment 8A established the discovery and architecture contract. Increment 8B
implements the exact Terraform/provider pins, data-source foundation, external
state boundary, static CI validation, and accepted read-only plan. Increment 8C
has accepted initial creation plus the controlled `DEFINED_ON_CORE` to `STARTED`
to `STOPPED` lifecycle. State-free bootstrap, reset/recreate, and NCDP cutover
compatibility are 8D.

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
  semantics. That transition is reserved for Increment 8D reset acceptance and
  is not routine stop behavior.

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
A later `DEFINED_ON_CORE` transition remains reset/wipe semantics reserved for
Increment 8D.

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

## State-free bootstrap and cutover

Credential-bearing startup configuration cannot pass through
`cml2_node.configuration`, `cml2_node.configurations`,
`cml2_lifecycle.configs`, `cml2_lifecycle.named_configs`, topology-embedded
configuration, or an equivalent out-of-band CML API write to those same stored
or day-zero fields. The payload can persist in state even when marked sensitive.
Merely omitting the fields from HCL is insufficient: provider `Read()` fetches
the CML node, and its Optional + Computed `configuration` and `configurations`
attributes can bring out-of-band stored configuration back into Terraform state
on refresh.

For the three Terraform-owned routers, Increment 8C explicitly sets
`configuration = ""`. This is a state-secrecy control, not managed network
intent: provider `0.9.3-beta1` can otherwise read CML node-definition default or
bootstrap configuration into Terraform state when the attribute is null. The
router field must never contain a credential-bearing or functional network
bootstrap configuration. No implicit CML bootstrap-generation action, including
CML **Bootstrap Lab** or an equivalent default-configuration generator, is part
of the accepted Terraform workflow. Runtime state-free bootstrap remains an 8D
responsibility. An empty stored configuration does not prove that a router will
later boot successfully; operational boot behavior requires separate
acceptance.

Existing stored CML configurations are also unsuitable as an adoption source:
their hostnames are placeholders, they are not authoritative runtime identity,
and a negative secret-pattern scan cannot prove arbitrary configuration
non-sensitive.

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
proven runtime channel that does not populate
provider-readable CML stored configuration
          |
          v
discard credentials and rendered payload
```

Increment 8D-1 accepts the CML browser console as the one-time manual IOS XE
runtime-bootstrap channel for the personal digital twin. The operator applies
bootstrap directly to the running device; Terraform retains infrastructure and
lifecycle ownership and never owns the runtime payload. Console-keystroke
automation was intentionally abandoned because it adds little value to the
end-to-end NCDP demonstration compared with a bounded manual bootstrap followed
by automated management-plane operation.

Increment 8D acceptance must prove all of these properties:

1. Credentials and rendered secret material are never persisted in CML stored
   configuration.
2. Credentials and rendered secret material are never present in Terraform
   plans or state.
3. A Terraform refresh after bootstrap does not recover secret-bearing data
   into state.

If no runtime bootstrap boundary can satisfy all three properties, 8D must stop
and revisit the architecture rather than weakening state secrecy.

The [Increment 8D-1 console feasibility acceptance](../acceptance/terraform-cml-console-bootstrap-feasibility-increment-8d.md)
proved those properties for a non-secret IOS XE runtime hostname. CML stored
configuration stayed zero length, Terraform refresh did not import active
running configuration, and the unsaved marker disappeared after restart. This
does not by itself accept management-IP or authentication bootstrap, SSH or
NETCONF, Junos bootstrap, reset/recreate, or NCDP cutover.

Increment 8D-2 accepts the next IOS XE boundary. The legacy lab is deliberately
kept stopped to remove its duplicate management identity, and `192.168.4.14`
now realizes the unchanged NetBox identity on Terraform-created `core-02`.
One-time manual console bootstrap persists management, the unchanged OpenBao
credential authenticates over strict SSH host trust, and the existing NCDP path
reaches read-only planning. Saved device configuration remains on the router
disk and outside CML stored configuration and Terraform state. See the
[Increment 8D-2 acceptance report](../acceptance/terraform-cml-iosxe-management-bootstrap-increment-8d.md).

After Increment 8D-2, the accepted legacy lab remains deliberately STOPPED to
prevent duplicate ownership of stable NetBox-managed endpoints. It has not been
deleted or retired. The Terraform-created realization now operationally owns
`core-02` at `192.168.4.14` for the accepted IOS XE compatibility path. Before
future NCDP operations, NCDP must continue to freshly verify NetBox identity,
OpenBao provenance, SSH host trust, platform, hostname, and topology. Permanent
legacy-lab retirement remains a separate later decision.

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
before the legacy runtime was restored. A later `DEFINED_ON_CORE` request is
reset/wipe semantics reserved for 8D. See the
[lifecycle acceptance report](../acceptance/terraform-cml-lifecycle-increment-8c.md).

### 8D — reset/recreate and NCDP compatibility

In progress. Increment 8D-1 accepts one-time manual CML browser-console
bootstrap for IOS XE and its state-free runtime boundary. Increment 8D-2 accepts
persistent IOS XE management/authentication bootstrap, the stable NetBox
identity's operational transfer from the stopped legacy realization, strict SSH
host-trust re-establishment, existing OpenBao credential reuse, and read-only
NCDP planning. Junos bootstrap, destroy/recreate and reset acceptance,
deterministic lifecycle reconciliation, full cutover, and legacy retirement
remain. Terraform controls CML infrastructure and lifecycle only, never
production configuration.
