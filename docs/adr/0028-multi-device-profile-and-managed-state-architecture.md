# ADR 0028: Multi-device profile and managed-state architecture

- Status: Accepted
- Date: 2026-08-31

## Context

NCDP's accepted execution platform safely manages one IOS-XE router and one
Junos router. Detour B will eventually extend the reference design with a
classic IOS router, a classic IOS switch, VLAN switching, OSPF, flow-oriented
security policy, network-level assurance, and protected multi-device delivery.

The current platform field, adapter dispatch, management-interface protection,
and CML realization encode assumptions that are valid for the accepted
two-device environment but cannot safely serve as the expanded domain model.
Changing those v1 fields directly would also alter serialized plans, evidence,
or digests before a reviewed migration boundary exists.

## Decision

Introduce additive, closed, typed architecture contracts outside the current v1
execution path:

- Network OS is `iosxe`, `ios`, or `junos`. IOSv and IOSvL2 share IOS.
- Operational role is separate and initially `core`, `edge`, `transit`, or
  `access`.
- Capabilities are supplied only by a reviewed Git-owned profile catalog and are
  never inferred solely from vendor or NOS.
- Automation-profile identities are `cat8000v_iosxe`, `iosv_159_3_m12`,
  `iosvl2_2020`, and `vjunos_router`.
- CML realization profile, image, resources, bootstrap, readiness, and
  interface-slot mapping are separate from stable inventory and automation
  behavior.
- Management binding separates physical attachment from the logical L3/IP-owning
  interface. A generic management binding contains no CML slot.
- The preferred future IOSvL2 management realization uses routed `Gi0/0` as
  both physical attachment and L3 owner. The generic binding still permits
  distinct physical and logical interfaces for other platforms.
- Management endpoint purpose is explicitly `LIVE` or `STAGING`. One logical
  device has exactly one of each on the same stable management interfaces, with
  distinct NetBox IP identities and addresses. Normal targeting may resolve
  only LIVE; an explicit staging realization/context may resolve only STAGING.
- Legacy SSH compatibility can only be profile-local, retains strict host-key
  verification, and is recorded for exact IOSv as requiring B2 real-adapter
  acceptance. B1 changes no transport.
- NetBox, Git, OpenBao, devices, and Terraform/CML state each receive the single
  authorities recorded in the
  [multi-device architecture contract](../architecture/multi-device-architecture-contract.md).
- A managed ownership envelope specifies exact normalized fields owned for one
  vertical and scope. Whole-running-config equality is not a drift contract.
- `AcceptedManagedStateRef` binds one versioned envelope, target/scope,
  normalized accepted desired-state digest, source commit, and durable
  acceptance evidence. Different verticals may have different D0 references.
- Managed scope identities use closed kind-specific NetBox namespaces or the
  Git-owned `git:policy:<safe-stable-token>` namespace.
- LIVE and STAGING are realizations of one logical network. Data-plane prefixes,
  addresses, VLANs, router IDs, endpoint addressing, OSPF intent, and security
  intent are identical; only externally reachable management endpoints differ.
- Stable logical device names are shared across realizations. Future lightweight
  `users-host-01` and `servers-host-01` traffic fixtures are not managed network
  devices or fleet members.
- A future coordinated service plan may use a small ordered phase vocabulary
  where ordinary fleet-prefix safety is insufficient. No arbitrary DAG or
  executor is introduced here.

Current v1 models, schema versions, serialized fields, canonical digest inputs,
adapters, renderers, Terraform topology, Buildkite graph, promotion input, and
delivery behavior remain unchanged. B2 must introduce an explicit migration
boundary before the new catalogs influence runtime selection.

## Current reference-environment relationship

[ADR 0024](0024-two-router-live-and-ephemeral-staging.md) remains current truth
for the live and disposable reference environment. This ADR does not claim that
`transit-ios-01` or `access-sw-01` exists, that any proposed management address
is available, or that the accepted two-device environment has expanded.

A future four-device reference-environment ADR will explicitly supersede ADR
0024 only after the new inventory, credentials, CML realization, read-only
validation, and acceptance evidence exist. Historical ADR 0024 will not be
rewritten.

## Consequences

Detour B gains a fail-closed architecture vocabulary without changing current
execution. IOS routing and IOS switching can share one real NOS while retaining
different reviewed behavior and realization profiles. IOSv legacy compatibility
cannot leak into IOS-XE or Junos profile policy. IOSvL2 uses routed `Gi0/0` for
preferred future management while retaining SVI capability for later data-plane
intent. Its initial role remains access switching; `core-02` owns inter-VLAN
routing.

The additive boundary deliberately defers NetBox integration, profile-based
adapter dispatch, collectors, durable baseline persistence, drift comparison,
candidate staging writes, multi-device execution, observability expansion, and
four-device acceptance to later increments.
