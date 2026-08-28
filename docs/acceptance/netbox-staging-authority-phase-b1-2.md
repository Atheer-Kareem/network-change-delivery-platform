# Phase B1-2: NetBox staging identity and homolog authority acceptance

Status: external NetBox authority complete; repository evidence pending review.

## Authority and scope

ADR 0023 and merged main
`ad6f77b08d5ff21087adfeef2c6c1de3881be9b7`, validated by natural Buildkite
Build #180, authorize this bounded NetBox-only increment. The operator selected
`192.168.4.30/24` for the Cisco staging homolog and `192.168.4.31/24` for the
Junos staging homolog after the preceding read-only candidate discovery.

The increment created persistent staging inventory authority only. It did not
create a CML realization, credential, Terraform resource, Buildkite change, or
device session, and it did not begin Phase B2. Increment 11A remains paused for
the ADR 0023 migration.

## Recovery chronology

B1-2 completed across two bounded REST-writer episodes:

1. The first temporary writer created operations 1 through 4 below through the
   NetBox REST API.
2. The local operation-5 guard stopped before issuing a PATCH because it
   incorrectly expected existing Device custom-field mappings to remain empty.
3. No automatic rollback occurred. The first writer was fully retired.
4. Independent read-back confirmed that NetBox 4.6.7 correctly materialized
   both newly applicable fields on existing Devices with `null` values.
5. The retained schema, role, and ObjectChange records were revalidated.
6. A distinct short-lived continuation writer resumed at operation 5 and
   completed the remaining authority.
7. Independent final read-back and model validation succeeded before the
   continuation writer was retired.

The correct pre-update state for devices 1, 2, and 3 was therefore:

```text
ncdp_environment = null
ncdp_live_homolog = null
```

No retained object was deleted, recreated, or renamed during recovery.

## Selected-address re-admission

Immediately before the continuation writer was created, `.30` and `.31`
remained absent from NetBox. The macOS host remained `192.168.4.4/24` on `en0`,
and both candidate routes were directly connected through that interface. Two
ICMP attempts per address produced no response; pre-check neighbor entries were
absent and post-check entries were incomplete with no MAC owner. A read-only
literal check across the sole stopped five-node CML lab found no `.30` or `.31`
claim. No subnet sweep, broad `nmap`, TCP, SSH, or NETCONF probe occurred.

These observations were secondary collision evidence only. Address authority
remained the accepted static/manual allocation policy and NetBox Prefix ID 1;
network silence was not treated as IPAM authority.

## NetBox schema and inventory

The resulting authority is:

| Object | ID | Accepted state |
| --- | ---: | --- |
| CustomFieldChoiceSet | 1 | `NCDP environments`; exact values `live`, `staging`, `scenario` |
| CustomField | 1 | `ncdp_environment`; optional `select`; applies only to `dcim.device`; choice set 1 |
| CustomField | 2 | `ncdp_live_homolog`; optional single `object`; applies to and references `dcim.device`; filter `{"id__in":[1,2]}` |
| DeviceRole | 2 | `NCDP Staging`; slug `ncdp-staging` |
| Device | 1 | `core-02`; active; environment `live`; homolog unset; original type, platform, tags, and primary IP retained |
| Device | 2 | `edge-junos-01`; active; environment `live`; homolog unset; original type, platform, tags, and primary IP retained |
| Device | 6 | `stg-core-02`; staged; site 1; role 2; device type 1; platform 1 `cisco-ios-xe`; environment `staging`; homolog device 1; no tags |
| Device | 7 | `stg-edge-junos-01`; staged; site 1; role 2; device type 2; platform 2 `juniper-junos`; environment `staging`; homolog device 2; no tags |
| Interface | 9 | device 6 `GigabitEthernet1`; `1000base-t`; enabled; not management-only; no tags |
| Interface | 10 | device 7 `fxp0`; `1000base-t`; enabled; not management-only; no tags |
| IPAddress | 9 | `192.168.4.30/24`; active; assigned to interface 9; primary IPv4 of device 6 |
| IPAddress | 10 | `192.168.4.31/24`; active; assigned to interface 10; primary IPv4 of device 7 |

Device 3 `core-03` remains active with original device type 1, platform 1,
primary IPAddress ID 3 (`192.168.4.15/24`), and fleet tag. Its environment and
homolog remain `null`; B1-2 did not delete, deactivate, or classify it.

The homolog filter on CustomField ID 2 is UI and selection convenience for the
current accepted pair. It is not authorization or integrity enforcement.
Protected staging code must independently require a staging-to-live mapping,
reject self or staging-to-staging references, verify environment and compatible
platform/profile, and require unique reverse mapping. Final read-back proved
exactly one staging reference to each live baseline device and matching device
type/platform pairs.

## Mutation journal and native provenance

All authoritative mutations used bounded NetBox REST API writers. Each produced
a native ObjectChange with an empty optional changelog message.

| Operation | Writer episode | REST result | ObjectChange | Request ID |
| ---: | --- | --- | ---: | --- |
| 1 | first | create choice set 1 | 4 | `517317b9-444a-4380-a67d-efb0f4bddde3` |
| 2 | first | create custom field 1 | 5 | `659bf982-6993-477b-8b2f-f8279e55a50f` |
| 3 | first | create custom field 2 | 6 | `542d4eca-20a0-4ea4-b064-e4faaaf81e61` |
| 4 | first | create device role 2 | 7 | `75972d1e-bfc7-4f4c-992e-cdf636f55625` |
| 5 | continuation | update device 1 environment | 10 | `8cbc2903-b4b4-456b-873f-68a544c49b76` |
| 6 | continuation | update device 2 environment | 11 | `2b24027e-ddf9-4f60-a8c2-69b980ee7eef` |
| 7 | continuation | create device 6 | 12 | `b4380706-9560-4587-8735-38f3bada7e7d` |
| 8 | continuation | create device 7 | 13 | `803e37c4-1a71-4bac-ab0d-e9c34224578c` |
| 9 | continuation | create interface 9 | 14 | `fc7d0830-5a02-48e5-9f61-571c2759c645` |
| 10 | continuation | create interface 10 | 15 | `5ac51216-c336-4c60-9aa2-5779bb4fa746` |
| 11 | continuation | create and assign IPAddress 9 | 16 | `bf3d1a14-2d44-4e86-bcb5-268b746e64a6` |
| 12 | continuation | create and assign IPAddress 10 | 17 | `fd578732-aa49-4709-aa22-354afd59cbb3` |
| 13 | continuation | update device 6 primary IPv4 | 18 | `b54f7785-d129-4f60-8a92-202b469452f4` |
| 14 | continuation | update device 7 primary IPv4 | 19 | `a262b418-b9fb-45e7-8306-8deea2281066` |

ObjectChanges 4 through 7 retain the first writer username
`ncdp-netbox-staging-b1-2-writer`. ObjectChanges 10 through 19 retain the
continuation username `ncdp-netbox-staging-b1-2-writer-r1`. Their timestamps
span `2026-08-28T05:26:05Z` and `2026-08-28T07:02:08Z` through
`2026-08-28T07:04:57Z`, respectively. Every record has the exact object type,
object ID, action, writer username, and request ID shown or described above.
No retrospective record was fabricated.

## Writer boundary and retirement

The continuation writer was a non-superuser with an unusable password and a
short-lived write-enabled NetBox v2 token. Its allowed sources were limited to
canonical and IPv4-mapped loopback, matching NetBox's observed local REST
source. Twelve ObjectPermissions limited reads and writes to the retained
schema/role/support objects, live devices 1 and 2, the two exact staging names,
their two exact interfaces, and `.30`/`.31`. Device 3 was view-only.

Before authoritative continuation, exact allowed reads returned HTTP 200;
device 3 PATCH returned 404; an unauthorized device create and `.32` IP create
returned 403. Independent database read-back found no residual object or
ObjectChange from those denial tests.

After final acceptance, the token was disabled and its bearer returned HTTP
403. The token, twelve permissions, group, user, private token file, and private
directory were then deleted. Final standing B1-2 writer privilege is zero.
Existing NCDP readers were not modified.

## Selector-negative and safety proof

The repository's canonical single-target and managed-population paths require
`status=active` and tag `ncdp-managed`. The fleet path additionally requires
its exact fleet tag and interface tag. Both staging devices are `staged`, have
role `NCDP Staging`, environment `staging`, and no tags. An actual read through
the existing NCDP NetBox provider returned only devices 1 and 2 for the managed
population and rejected both staging names as inactive.

The historical live fleet selector returned no staging object, then failed
closed on the pre-existing device 3 because it is fleet-tagged but lacks
`ncdp-managed`. That existing core-03 condition is outside B1-2 and was not
changed. It does not make either staging identity eligible for a canonical live
target path.

This increment made zero CML, OpenBao, Terraform, Buildkite-configuration,
device, persistent-service, Oxidized, AuditStore, or observability mutation.
It opened no device session. B2 and 11B did not start, and 11A remains paused.
