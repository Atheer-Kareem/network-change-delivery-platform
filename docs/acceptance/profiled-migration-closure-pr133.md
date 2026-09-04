# Profiled migration closure acceptance — PR 133

## Scope and authority

This acceptance closes Detour B against implementation commit
`5e2df7a86698e778016a55f80828bc405cd425b5` on
`feat/detour-b-profiled-migration-closure` in PR 133. It was deliberately split
into two reviewed stages. Across both stages there were zero network-device
configuration writes, zero CML mutations, and zero B5/D0 mutations. Buildkite
runtime state was not inspected.

The final managed population is the exact Git-owned profiled population:

- `netbox:dcim.device:1` — `core-02`
- `netbox:dcim.device:2` — `edge-junos-01`
- `netbox:dcim.device:8` — `transit-ios-01`
- `netbox:dcim.device:9` — `access-sw-01`

Population membership does not grant write capability. Interface-description
write admission remains limited to the C8000V IOS-XE and vJunos profiles.

## Stage 1 — legacy NetBox marker retirement

The accepted local NetBox administrative boundary proved that
`ncdp-managed` was assigned to exactly devices 1/2 and that
`ncdp-profiled-inventory` was assigned to exactly active devices 1/2/8/9. One
atomic transaction removed only the two `ncdp-managed` many-to-many tag
assignments. The Tag object was retained with zero device assignments. All
unrelated tags on devices 1/2 were preserved, and devices 8/9 were unchanged.

Fresh read-only reconciliation proved:

- `ncdp-managed` assignments: zero;
- `ncdp-profiled-inventory`: exactly devices 1/2/8/9, all active;
- `NetBoxProfileInventoryProvider`: exact identities, names, and accepted
  profiles for devices 1/2/8/9;
- profiled LIVE verification: exact CML anchors, trust, profile bindings, and
  read-only collection passed for all four devices;
- management observability: exact-four profile-derived management endpoints;
- SNMPv3 SHA256/AES128: capability-derived projection of devices 1/2; and
- B5: the same four generation-one `INITIAL_ADOPTION` records, byte-for-byte.

Stage 1 then stopped safely because the existing private Oxidized materialized
source still contained only `netbox-device-1` and `netbox-device-2`. The
successful NetBox mutation was not repeated.

## Stage 2 — Oxidized reconciliation

A separately reviewed continuation ran the current persistent Oxidized
reconciler exactly once. It used the existing dedicated Oxidized bootstrap
authority to issue one bounded source SecretID under the accepted TTL and use
limits. It did not change any OpenBao role, policy, mount, auth method, KV
credential, username, or password.

The reconciler atomically refreshed the private source from exact-two to these
four nodes:

- `netbox-device-1`
- `netbox-device-2`
- `netbox-device-8`
- `netbox-device-9`

Because the source changed, the owned Oxidized container was recreated. Fresh
checks proved its accepted read-only/container definition, loopback-only API,
exact-four `managed` node metadata, strict exact-four host trust, and current
exact-four readiness marker. `oxidized_source.py` resolves
`NetBoxProfileInventoryProvider.resolve_profiled_population()` and has no
`ncdp-managed` dependency.

Private configuration-history HEAD and commit count did not change during the
reconciliation. Its current tree already represents all four managed node
names. No configuration content or credential value was included in acceptance
output.

Final read-only reconciliation reconfirmed zero `ncdp-managed` assignments,
the exact-four profiled inventory and management observability population, and
the SNMP capability projection of devices 1/2. The B5 before/after file list
and SHA-256 hashes were identical: four generation-one `INITIAL_ADOPTION`
records, no generation two, no `POST_WRITE_VALIDATED`, and no D0 advancement.

## External mutation accounting

Across both stages:

- NetBox persistent mutations: exactly two previously accepted tag
  detachments, with no NetBox mutation in Stage 2;
- local Oxidized: the private source and owned container/readiness were
  reconciled to exact-four;
- OpenBao persistent authority/credential mutations: zero; Stage 2 issued one
  bounded source SecretID;
- network-device configuration writes: zero;
- CML mutations: zero; and
- B5/D0 mutations: zero.

## Conclusion

Detour B migration is closed. Current architecture has one profiled exact-four
managed population with explicit per-profile capability projections. The
schema-v1 execution engine, protected delivery, and disposable exact-two
staging are retired. B4 routed-underlay, OSPF, VLAN/trunk, and ACL desired states
remain un-applied D1 proposals, and B5 remains unchanged.
