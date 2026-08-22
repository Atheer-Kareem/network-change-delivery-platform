# NetBox inventory acceptance — Increment 3

## Scope and environment

Acceptance ran on 2026-08-22 against NetBox 4.6.7 using upstream netbox-docker
5.0.2 and image `docker.io/netboxcommunity/netbox:v4.6.7-5.0.2`. The resolved
multi-platform image digest was
`sha256:7ad3a287d38829c98799c4a03d874d3d309738d1f42987dfd8037ec0e80587ce`;
the accepted host used its `linux/arm64` manifest
`sha256:a5083949460b182c2fe73206e3aff76663ce11967949517302b998484dfd6439`.
The upstream stack was held only under ignored `.local/` state and NetBox was
published as `127.0.0.1:8000`, not on all Mac interfaces.

The API reported `netbox-full-version` `4.6.7-Docker-5.0.2`. The NCDP identity
was a dedicated enabled v2 token, expiring after 30 days, with
`write_enabled = false` and object permission limited to viewing devices and
interfaces. Secret and service credential values were not retained in evidence.

## Synthetic inventory evidence

- Provider source: `netbox`
- Device: `core-02`, active and tagged `ncdp-managed`
- Stable object identity: `netbox:dcim.device:1` (local synthetic object)
- Platform mapping: NetBox `cisco-ios-xe` to internal `cisco_iosxe`
- Primary IPv4: `192.168.4.14/24`, normalized endpoint `192.168.4.14:22`
- `GigabitEthernet1`: tagged `ncdp-protected` and returned in normalized protection metadata
- `GigabitEthernet2`: present without the `ncdp-protected` tag
- NetBox interface descriptions: empty and not consumed as desired configuration

The production adapter resolved this data over the loopback HTTP exception using
Bearer authentication. No production provider call issued a non-GET request.

## Live read-only result

The existing device environment credentials were used for read-only Ansible
collection after NetBox resolution. The device reported hostname `core-02`, IOS
XE version `17.18.02`, and current `GigabitEthernet2` description
`managed-by-network-change-delivery-platform`. Identity and interface safety
validation passed; the interface was not protected.

`ncdp plan --netbox` returned `interface is already compliant; no deployable
artifact produced`. No plan file was produced. The deploy command was not run,
the execution adapter was never invoked, and no `ios_config`, configuration
write, startup-config save, or NetBox mutation occurred during normal NCDP
execution. Device writes: zero.

## Limitations

This acceptance covers one exact personal-lab device and read-only no-op planning.
It does not cover selectors, fleets, Junos, custom SSH ports, NetBox writes,
OpenBao, Buildkite deployment, Batfish, CML lifecycle, or observability. Existing
environment-provided SSH credentials remain temporary; OpenBao is the next
bounded Increment 3 step.
