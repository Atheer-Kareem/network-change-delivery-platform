# ADR 0029: Profile-bound read-only inventory and transport admission

- Status: Accepted
- Date: 2026-08-31

## Context

[ADR 0028](0028-multi-device-profile-and-managed-state-architecture.md)
separates network OS, operational role, capability, automation behavior, CML
realization, and LIVE/STAGING management identity. Those contracts were
architecture-only in B1. Directly expanding the v1 `InventoryDevice` platform
field or its two-platform adapter dispatch would change accepted plan and
evidence schemas before the four-device authority exists.

The local NetBox authority already contains useful factual identity for the two
accepted devices, but it does not yet contain the B2 management-purpose or
operational-role metadata. The Cisco v1 adapter also deliberately forces
Paramiko, whereas B2 needs exact profile-local backend admission without
changing that accepted write-capable path.

## Decision

B2 introduces a parallel, versioned, read-only path:

- `ProfiledInventoryDevice` freezes stable NetBox device identity, factual
  platform and device-type identity, independently resolved operational role,
  `NetworkOS`, exact automation and CML-realization profile references, the full
  `ManagementEndpointSet`, and protected stable interfaces. It contains no
  credential or configuration.
- Factual NetBox platform slug maps to `NetworkOS`. The exact pair of platform
  slug and device-type slug maps through a closed Git-owned admission catalog to
  one automation profile and one CML realization profile. There is no hostname,
  IP-address, role, or fallback-based profile selection.
- Operational role is resolved only from exact NetBox role slugs `core`, `edge`,
  `transit`, and `access`. Role never selects behavior.
- NetBox IP tags `ncdp-management-live` and
  `ncdp-management-staging` provide semantic endpoint purpose. Interface tag
  `ncdp-management-attachment` identifies the physical management attachment.
  Purpose is never inferred from primary/secondary position or numeric address.
- Both management IPs remain NetBox-owned, active, explicitly interface-assigned,
  and protected. LIVE must exactly match `primary_ip4`; STAGING must be a
  distinct non-primary IP object and address. The generic physical/L3 split
  from B1 remains valid.
- The B2 provider resolves the complete endpoint set but exposes only
  `live_read_only_target()`. There is no general endpoint-purpose selector and no
  STAGING projection. B3 must introduce an explicit staging realization/context
  before STAGING can become a connection target.
- `ProfileReadOnlyAdapter` exposes only normalized discovery and exact-interface
  collection. It has no execute, transaction, confirmation, recovery, or SNMP
  write surface.
- Exact dispatch is `cat8000v_iosxe`, `iosv_159_3_m12`, and `iosvl2_2020` to
  Cisco Ansible read-only collection, and `vjunos_router` to PyEZ/NETCONF
  read-only collection. Unknown or mismatched profiles fail closed.
- Cisco SSH backend admission is profile-local: CAT8000V uses libssh, exact IOSv
  M12 uses Paramiko, and IOSvL2 uses libssh. Every path requires pre-existing
  host trust, host-key checking, and disabled auto-add. No backend fallback or
  global SSH algorithm relaxation is admitted. Junos retains its existing
  hardened PyEZ/NETCONF path.

The existing v1 provider, models, plans, adapters, Buildkite deployment,
staging driver, promotion artifacts, and digests remain unchanged. Existing
write methods continue to accept only v1 `InventoryDevice`, and v1 Cisco
execution continues to force Paramiko.

## NetBox and reference-environment relationship

The read-only audit and B3 migration requirements are recorded in the
[profile-bound inventory architecture](../architecture/profile-bound-read-only-inventory.md).
B2 performs no NetBox mutation. Missing tags and role slugs therefore make the
current two devices ineligible for B2 profile resolution until B3 performs a
separately reviewed authority migration.

[ADR 0024](0024-two-router-live-and-ephemeral-staging.md) remains current truth
for the two-device live and disposable reference environment. B2 creates no
IOSv or IOSvL2 device, address, credential, CML node, VLAN, prefix, or
data-plane intent. B3 will own the separately reviewed NetBox authority mutation
and four-device realization work.

## Consequences

B2 can test closed profile admission and provider collection without silently
changing protected delivery. IOSv and IOSvL2 remain one IOS NOS while their
device-type facts select different reviewed behavior. LIVE/STAGING identity is
explicit before either endpoint can be used, and ordinary code cannot obtain a
staging target.

The new source is runtime-relevant, so normal PR assurance and current
two-device disposable staging provide useful non-regression evidence. They do
not create B2 write authority or claim four-device acceptance. Real IOSv and
IOSvL2 backend acceptance remains bounded by existing credentials and trusted
host keys; absence of those inputs is reported rather than bypassed.

Bounded B2 acceptance passed the existing Junos PyEZ profile. CAT8000V libssh
stopped at strict host trust even though the accepted trust source contains its
`ssh-rsa` key. The bounded result does not prove the exact negotiation cause,
so this ADR authorizes no fallback, algorithm override, or weakened checking;
CAT8000V strict-profile acceptance remains unresolved. Temporary IOSv and
IOSvL2 acceptance remains pending explicit credentials.
