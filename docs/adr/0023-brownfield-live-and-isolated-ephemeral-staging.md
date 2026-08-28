# ADR 0023: Brownfield persistent live-reference and isolated ephemeral CML staging

## Status

Accepted for architecture and phased migration implementation. This decision
does not itself authorize CML, NetBox, OpenBao, Terraform-state, device, or
persistent-service mutation. Each migration phase requires separate review and
acceptance.

## Context

NCDP first delivered protected changes to an accepted manually built Personal
CML lab. ADR 0012 later introduced a separate Terraform-owned twin to prove
reproducible infrastructure creation without importing or adopting that lab.
ADR 0014 made CI staging ephemeral after fresh-first-boot validation succeeded
while same-realization vJunos restart proved unsuitable as a routine staging
lifecycle.

Protected delivery, Oxidized, and Increment 11A subsequently reused a
disposable operator twin because staging and the manual lab shared canonical
NetBox identities and management addresses. That model preserved exclusive
endpoint ownership, but ordinary post-merge acceptance repeatedly required
creation, first boot, trust enrollment, admission, retirement, and destruction
of an entire CML realization.

The existing manual lab is deliberately independent of Terraform staging and
its Day-0 source. That independence is useful: observed differences can reveal
either legitimate live drift or an incorrect NCDP platform assumption. The
platform must classify the difference before anyone remediates the live
environment. It must also demonstrate the common brownfield boundary in which
automation is introduced to infrastructure that already exists.

The accepted manual lab has historical UUID
`09605569-0468-4fc4-8684-beb5a1342b9c` and historical title
`Lab at Wed 21:44 PM`. A later controlled rehabilitation may rename that same
lab under explicit operator authority before onboarding. It remains a personal,
production-like reference environment, not production.

## Decision

### Environment classes

There are exactly three environment classes:

1. **Brownfield live/reference.** The existing manual CML lab is persistent,
   normally running after rehabilitation, and owned by the CML operator. Its
   active managed-device baseline contains only the retained `core-02` and
   `edge-junos-01` pair. It becomes the protected-deployment target, live
   Oxidized source, and continuous-observability realization.
2. **Ephemeral staging.** Terraform and Buildkite own a fresh, run-scoped
   Cisco/Junos homolog pair with separate inventory, addressing, credentials,
   and CML realization identity. Its lifecycle remains fresh create, first
   boot, readiness, validation, sanitized evidence, destroy, and proven
   absence. It is never a protected live target.
3. **Explicit scenarios.** Terraform owns disposable, purpose-specific
   environments for additional platforms, larger fleets, three-router
   topology, replacement, restart/recovery, scale, and other reviewed tests.

There is no ordinary fourth operator-twin environment. Existing operator-twin
code may remain temporarily during migration, but Terraform must not regain
live authority through a renamed wrapper.

### Live authority matrix

| Property | Authority |
| --- | --- |
| Lab, nodes, images/definitions, CPU/RAM, cabling, connector, lifecycle, replacement, and deletion | CML operator / manual infrastructure |
| Stable device/interface identity, platform, role, environment, canonical management address, and targeting/protection metadata | NetBox |
| Device credentials | OpenBao |
| Current realization identity | Observed CML metadata plus reviewed private onboarding/admission evidence |
| Explicitly accepted managed-intent scopes | Git/NCDP |
| Actual configuration chronology | Oxidized private Git |
| Operational metrics | Prometheus |
| Protected-delivery evidence | AuditStore |

Terraform must never import, adopt, manage, converge, replace, stop, start, or
destroy the brownfield live lab or its resources. CML UUIDs are realization
evidence and never stable NetBox identity.

Git/NCDP owns only configuration scopes for which an explicit managed-intent
contract has been accepted. The current interface-description scope remains
Git/NCDP-managed. Existing brownfield configuration outside declared scopes is
observed, unmanaged state until a separate authority and implementation
decision deliberately onboards it. VLANs, routing, ACLs, additional interface
intent, and network services are not automatically managed merely because the
device is onboarded. No overlapping authority is allowed inside an explicitly
managed scope.

### Manual bootstrap boundary

Manual bootstrap is limited to what is needed to create and onboard the
pre-existing device: CML lab/node existence, node image/definition, CPU/RAM,
connector and cabling, platform boot prerequisites, identity hostname,
management interface and address/mask, a management VLAN only when required
for reachability, a bounded local management account, SSH, Junos NETCONF, and
minimum platform prerequisites.

Anything beyond that boundary is either an explicitly accepted NCDP-managed
scope or pre-existing observed/unmanaged brownfield state. Onboarding does not
silently move the latter into NCDP authority.

### Baseline topology and fidelity

Running CML `core-03` is not required by the current protected deployment,
immutable plan/request, live NetBox devices 1 and 2, Oxidized, Increment 11A,
or audit schemas. A later controlled rehabilitation may remove its CML
realization. NetBox device 3 is not automatically deleted. Historical and
synthetic three-device Batfish, promotion, and fleet evidence remains valid.

The future brownfield active baseline and staging baseline each contain a Cisco
and Junos managed pair. Baseline staging is expected to contain one lab, an
external connector, a management switch, two routers, four links, and one
lifecycle resource: ten Terraform resources. The implementation and exact graph
remain a later migration decision.

Historical discovery found no recorded data-plane links among the live NCDP
routers; they connected only through the management fabric. The Batfish
three-router chain is synthetic assurance input, not observed CML wiring. A
staging homolog is therefore a device, platform, and automation-role homolog,
not necessarily an exact topology clone of brownfield live. A direct
Cisco--Junos staging link is staging/integration topology. Staging must not be
described as an exact live-topology digital twin. Exact topology fidelity needs
a separate reviewed decision.

### Staging identity, network, and credentials

NetBox will own two stable staging objects: a Cisco homolog of live `core-02`
and a Junos homolog of live `edge-junos-01`. Numeric IDs are deferred. Each
object requires `staging` environment classification, a compatible
platform/profile, staging address and eligibility, and an explicit NetBox-owned
homolog relationship. Names such as `stg-core-02` are context only; names and
CML tags are not homolog authority.

The preferred management design is a dedicated isolated staging network. A
fallback uses distinct staging addresses on the existing reachable management
fabric. ADR 0023 selects neither subnet nor connector. A read-only feasibility
increment must assess CML connectors, VLAN/trunk behavior, host and Buildkite
routes, firewall boundaries, and NetBox IPAM. Parallel operation requires
accepted address/network separation and capacity evidence.

Staging uses separate device credential objects and workload policies.
Terraform receives only staging/scenario credentials. Buildkite staging cannot
read canonical live paths, and live protected identities do not receive staging
paths by default. Prometheus and Blackbox remain device-credential-free. ADR
0013 credential-bearing Terraform Day-0 becomes a staging/scenario boundary;
brownfield live bootstrap uses a separately reviewed manual procedure.

### Brownfield drift and admission

Observed live differences are classified before remediation. The finite design
space includes inventory, realization, platform/image, management-address,
hostname/identity, SSH-trust, explicitly managed configuration,
unmanaged/brownfield configuration, bootstrap, topology, operational-state,
platform-assumption, and ambiguous/unclassified differences. Material authority
ambiguity fails closed. A legitimate platform representation rejected by NCDP
is investigated as a possible platform-assumption defect rather than changed on
the device merely to satisfy automation.

The live admission assertion is:

> This manually owned CML realization has been explicitly reviewed and admitted
> as the current embodiment of the canonical live NetBox devices.

A future private onboarding record may bind schema, controller identity,
environment, lab UUID/title, node UUIDs and labels, definitions/images,
endpoint markers, a sanitized structural/topology digest, canonical NetBox
identities, review metadata, freshness policy, and canonical digest. It is
operational admission evidence, not managed-configuration authority, and cannot
alone authorize a write. Material mismatch and relevant node replacement
invalidate it. Its exact schema is deferred.

Manual live infrastructure changes require explicit operator intent,
pre-change structural capture, consumer readiness invalidation where needed,
post-change validation, trust renewal after replacement, and evidence. No
Terraform run, Buildkite job, monitoring alert, or reconciler automatically
converges live CML infrastructure.

### Protected deployment

The future protected path is:

```text
ephemeral staging homolog validation
  -> promotion
  -> merge and exact main/build/request binding
  -> human approval
  -> persistent brownfield live realization verification
  -> strict host trust
  -> PRE actual-state observation
  -> fresh live preflight
  -> one protected execution attempt
  -> independent post-validation
  -> POST observation
  -> immutable evidence
```

Staging proves code, compatible platform behavior, and the reviewed homolog
contract; it does not prove current live state. Ordinary deployment performs no
CML create, start, stop, or destroy. ADR 0021's one-attempt, no-retry,
no-automatic-rollback, PRE/POST, immutable parent/child,
`TEMPORALLY_BRACKETED`, and `NOT_PROVEN` contracts remain.

### Oxidized

Oxidized continuously observes only the persistent brownfield live pair. Stable
NetBox source identities and private chronology continue across CML realization
replacement. Strict host verification and realization-bound readiness remain;
staging configuration never enters live chronology.

A manual node replacement invalidates readiness, retires old trust, requires
new realization verification and explicit host-key enrollment, and publishes
new readiness before collection resumes. Terraform is not involved.

### Continuous observability

Increment 11A will admit the persistent brownfield live pair. It retains stable
NetBox metric identity, credential-free TCP probes, source-commit binding,
atomic target publication, persistent TSDB, scheduled revalidation, and the
finite `SETTINGS`, `ADMISSION_READ`, `CML_REVALIDATION`, and
`ADMISSION_PUBLICATION` diagnostics.

After staging is separated, staging may coexist with live and its existence is
not by itself an admission failure. Live admission fails if another
realization claims the canonical live NetBox identity where authoritative, the
canonical `.14`/`.20` endpoints, or protected-live realization authority.
Successful 11A acceptance leaves live running, two targets ACTIVE, readiness
valid, and Prometheus/Blackbox and TSDB persistent. It does not retire targets
merely because acceptance completed.

### Capacity and vJunos recovery

Capacity evidence is historical. Removing baseline `core-03` materially lowers
consumption, and the declared staging router pair is 5 vCPU and 10,240 MiB, but
the manual live pair must be freshly measured. Concurrent acceptance must
observe peak and low-water capacity across staging creation, boot, readiness,
validation, and destruction and define a justified margin in that increment.
ADR 0023 fixes no permanent numeric reserve.

ADR 0014's fresh-first-boot model remains correct for staging. Brownfield live
normally runs continuously; same-realization stop/start recovery is not assumed
reliable. An unexpected vJunos restart failure is an operational incident and
may require manual replacement/bootstrap. Replacement changes CML UUID and
host key, while NetBox identity and Oxidized chronology remain stable;
re-onboarding and trust renewal are mandatory. Terraform does not recover live.

### Recovery material

Sanitized structural metadata may be retained as evidence. Full CML exports,
stored Day-0 content, bootstrap configuration, and equivalent recovery material
are privileged private data: they require separately reviewed storage and must
not enter source Git or normal Buildkite artifacts. Recovery combines reviewed
manual procedure with NetBox identity, OpenBao credentials, Oxidized chronology,
and any accepted private export.

## Migration

Migration is phased and fail closed:

1. **Architecture authority:** accept this ADR without infrastructure mutation.
2. **Staging separation:** perform network feasibility discovery; create
   staging NetBox identities, homolog authority, IPAM/network, OpenBao roles and
   credentials; reduce staging to the two-router Terraform baseline; accept its
   isolated ephemeral lifecycle.
3. **Brownfield rehabilitation:** freshly inspect structure, prepare private
   recovery, approve the exact removal list and optional lab rename, manually
   remove obsolete resources, start the retained pair, observe before
   remediation, and classify drift.
4. **Live onboarding:** reconcile NetBox and OpenBao provenance, admit the
   realization, establish trust and Oxidized baseline, perform read-only NCDP
   validation, and admit 11A.
5. **Consumer cutover:** move 11A first, Oxidized continuous operation second,
   and protected deployment last.
6. **Obsolete-contract retirement:** remove disposable operator lifecycle,
   legacy-stopped and shared-live-address staging assumptions, stale topology
   counts, and obsolete wrappers.

Every phase requires an explicit stop and rollback boundary. Increment 11A
remains paused until staging is separated, brownfield live is rehabilitated and
admitted, and 11A no longer depends on disposable-operator assumptions. Its
existing runtime, TSDB, CML 2.10 parser, source binding, refresh diagnostics,
and fail-safe publication evidence remain valid.

## Consequences

The architecture gains a realistic brownfield automation boundary, independent
assumption validation, concurrent isolated staging, persistent live chronology,
and meaningful continuous observability. It also adds manual-live governance,
staging inventory and credential objects, network-isolation work, onboarding
evidence, capacity measurement, and private recovery requirements. Live and
staging can drift, so their homolog contract must be continuously explicit.

## Superseded and preserved decisions

- ADR 0011 retains protected identity, credential, plan, and write controls;
  its live target is clarified as admitted brownfield live.
- ADR 0012's refusal to import/adopt the manual lab is reinforced. Its
  legacy-stopped/shared-address consequence is superseded only after staging
  separation.
- ADR 0013 applies Terraform credential-bearing Day-0 to staging/scenarios
  after migration; brownfield bootstrap is separately governed.
- ADR 0014 remains accepted for ephemeral staging.
- ADR 0020 retains strict host trust and chronology but its Terraform-owned
  fresh-realization and routine-destroy assumptions are superseded.
- ADR 0021 retains protected PRE/write/POST and durable correlation but its
  per-build operator-twin preparation/destruction is superseded.
- ADR 0022 retains stable identity, credential-free probing, source binding,
  TSDB, fail-safe publication, and periodic revalidation. Its disposable
  operator and blanket staging-absence assumptions are superseded.

Historical acceptance evidence is not rewritten; it records the correct
architecture and behavior at the time.

## Deferred decisions

The staging connector/network and subnet, staging IPs and NetBox IDs, exact
homolog representation, current manual-live structure and capacity, onboarding
schema, drift model implementation, private recovery/export process, exact
manual removal list, and optional live-lab rename remain later reviewed work.
