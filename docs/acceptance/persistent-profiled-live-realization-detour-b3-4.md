# Detour B3-4 persistent profiled LIVE acceptance

- Date: 2026-08-31
- Persistent lab: `NCDP Live`
- Lab UUID: `09605569-0468-4fc4-8684-beb5a1342b9c`
- Final CML state: `STARTED`
- Final population: six nodes, nine links

## Exact realization

| Logical device | NetBox ID | CML UUID | Definition | Image | State | LIVE service |
|---|---:|---|---|---|---|---|
| `core-02` | 1 | `59fc118d-dfa3-4a45-a905-6a056b591550` | `cat8000v` | `cat8000v-17-18-02` | `BOOTED` | `192.168.4.14:22` |
| `edge-junos-01` | 2 | `3ee87d9c-09b5-4ed2-a655-092bf89b1190` | `vjunos-router` | `vjunos-router-23-2r1-15` | `BOOTED` | `192.168.4.20:830` |
| `transit-ios-01` | 8 | `b6a5e482-a867-4b88-addc-02eb068afb84` | `iosv` | `iosv-159-3-m12` | `BOOTED` | `192.168.4.16:22` |
| `access-sw-01` | 9 | `fee01570-a8c6-478c-9e29-ebb991335346` | `iosvl2` | `iosvl2-2020` | `BOOTED` | `192.168.4.17:22` |

The remaining two nodes are the accepted external connector UUID
`9155d0a4-e72b-4ab9-9f62-8d485de3ace0` and management switch UUID
`e4542ca6-6fa9-46c6-bc95-6b437a8f270a`.

The realized links are:

| CML link UUID | Endpoints |
|---|---|
| `80587f5c-4e5f-4552-8496-2ab9110f53e3` | external connector to management switch |
| `ec2cac84-32d2-4628-a2a0-d4766f231105` | management switch to `core-02/GigabitEthernet1` |
| `dfa3c1fc-fc56-4935-9c26-71722de48bca` | management switch to `edge-junos-01/fxp0` |
| `5e171308-9e12-48ec-b968-2218f7aa7a4d` | management switch to `transit-ios-01/GigabitEthernet0/0` |
| `12fd7b69-c1d2-4717-9475-f4a42f0184cd` | management switch to `access-sw-01/GigabitEthernet0/0` |
| `8eee9cd3-56f5-4d99-a48e-4e4a35bc007a` | `core-02/GigabitEthernet4` to `edge-junos-01/ge-0/0/0` |
| `6613000c-9e14-42a4-bf8f-db00fbfe9982` | `core-02/GigabitEthernet2` to `transit-ios-01/GigabitEthernet0/1` |
| `1482adb5-a013-40ff-bd6e-e8668c47192d` | `edge-junos-01/ge-0/0/1` to `transit-ios-01/GigabitEthernet0/2` |
| `e905d765-862e-438f-8532-c65390eb0483` | `core-02/GigabitEthernet3` to `access-sw-01/GigabitEthernet0/1` |

No data-plane service configuration was applied. Transit
`GigabitEthernet0/3`, Junos `ge-0/0/2`, and access
`GigabitEthernet0/2-3` remain physically spare for later increments.

## Bootstrap and Junos reconciliation

The new IOS devices used only the exact OpenBao credentials keyed to NetBox
devices 8 and 9. Passwords remained in memory. CML stored configuration and IOS
running configuration contain only IOS type-9 scrypt verifiers. The accepted
stored-configuration digests are:

- transit: `sha256:c8418316128623c53d34e84c07f628f51dfaf4df3eb51d36280ceb4d24fdfbc8`;
- access: `sha256:25d40974443db6b1067e50cc55764ff0bb6dcead0a607e2e96d952d561ceebe8`.

`access-sw-01/GigabitEthernet0/0` is independently anchored as routed
management with `no switchport` and `192.168.4.17/24`.

The original Junos UUID `c4dc63a7-e6a2-41e0-a9f0-98e607cd6ebd` failed to
reapply its stored Day-0 after reboot. With explicit operator authorization, the
node and its three incident links were wiped and deleted, then the node was
recreated from the preserved Day-0 digest
`sha256:f82e47a299c943fd70a90f5f1e3e8e87d8e86ac15ef7a4215bee423524f8d0ff`.
The old CML UUID is retired and cannot be recovered in place; stable NetBox ID
2, logical name, configuration, image, management endpoint, and topology were
preserved under the new UUID recorded above.

## CML-anchored LIVE trust

The private profiled LIVE generation contains exactly four entries. CML
identity, image, state, hostname, and management-address evidence was admitted
before observing each network-visible key.

| Device | Key type | SHA256 fingerprint |
|---|---|---|
| `core-02` | `ssh-rsa` | `SHA256:mNQp+RgW/Rudeag+8Keh0OAQTMF2bwLhb1MkX9sCwXg` |
| `edge-junos-01` | `ssh-ed25519` | `SHA256:kxjA32myBRJG1OUkKvnEeQim2wUvpW/zoj5WpOd+MgI` |
| `transit-ios-01` | `ssh-rsa` | `SHA256:ag/u2+iXzrP0uF2d6iRAgMqL3saGcHS48vkQw9mfRFA` |
| `access-sw-01` | `ssh-rsa` | `SHA256:OufqmBRB/ePP9gaMZKk8hswtGTAFek9f+6Tu+3BZmGA` |

Known-host generation digest:
`sha256:06774193fc6f1b05b7cf87b62d11abbc7fbb6741f3cfef0444d0842f5cd5c305`.

No trust re-enrollment of the existing devices, ambient trust, network-only
decision, auto-add, disabled checking, fallback, or algorithm override was
used. The existing Oxidized exact-two known-host and metadata bytes remained
unchanged.

## Inventory and read-only acceptance

NetBox devices 8 and 9 changed from `planned` to `active` only after CML
readiness, OpenBao authentication, and CML-anchored trust passed. They retain
`ncdp-profiled-inventory` and do not have `ncdp-managed`.

- `resolve_profiled_population()`: exact devices 1, 2, 8, and 9 — **PASS**.
- `resolve_managed_devices()`: exact devices 1 and 2 — **PASS**.
- Persistent realization digest:
  `sha256:5e34053d178713b652b5c758763d902550bfb8bc48d6a4d1a3926326e7a388a6`.

Real `ProfileReadOnlyAdapter` results with strict host trust and exact OpenBao
credential selection:

| Device | Profile | Observed software | Interface count | Result |
|---|---|---|---:|---|
| `core-02` | `cat8000v_iosxe` | IOS XE `17.18.02` | 4 | PASS |
| `edge-junos-01` | `vjunos_router` | Junos `23.2R1.15` | 42 | PASS |
| `transit-ios-01` | `iosv_159_3_m12` | IOS `15.9(3)M12` | 4 | PASS |
| `access-sw-01` | `iosvl2_2020` | IOS `15.2(20200924:215240)` | 4 | PASS |

## Unchanged boundaries

Legacy v1 schemas, digests, `ncdp-managed`, Oxidized population and trust,
Prometheus/Blackbox target population, SNMP authority, protected device-write
authority, Terraform staging topology, VLAN/OSPF/ACL intent, disposable CML
staging, and protected delivery are not expanded. Automatic disposable staging
and protected delivery remain paused pending an explicit operator decision.
