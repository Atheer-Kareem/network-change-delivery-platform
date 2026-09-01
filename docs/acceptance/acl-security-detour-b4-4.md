# Detour B4-4 ACL security acceptance

## Outcome

Detour B4-4 adds one proposed Git-owned IPv4 security policy to the accepted
profiled candidate. USERS may reach SERVERS using HTTPS/TCP 443; other
USERS-to-SERVERS IPv4 traffic is denied; other directions remain permitted.
The ACL is outbound on core `GigabitEthernet3.20`, so traffic routed toward
SERVERS crosses the policy while independently initiated SERVERS-to-USERS
traffic does not. This is directional packet filtering, not stateful firewall
semantics.

No device configuration or external authority was changed. B4-4 is proposal
and assurance evidence only; it is not D0 and grants no execution authority.

## Authority, observation, and proposed state

The proposal consumes the unchanged B3-5 allocation
`sha256:1352521feec8f787eb1a468c586dd3390428289314c3984416ab987a8af61b3d`,
the B4-3 VLAN/gateway allocation
`sha256:3068c48d95639a5f46cffefd53b0f778399b06a58b1a0704cd02e2a9dd338a1b`,
and the accepted VLAN D1
`sha256:57fe2decfcf6ecaf595a877fac9d2fa4befa0286ec7a70b8235fd514ca3995b3`.
Git owns `git:policy:users-servers-https`; no NetBox ACL object or tag exists.

The final LIVE observation used the normal stable-ID `OpenBaoSecretProvider`,
the exact profiled trust generation, and the closed `acl_security_policy` read
scope. The Cisco adapter owns its immutable reviewed `show` tuple; arbitrary
CLI cannot reach Runner. The bounded AppRole acceptance material was retired
after collection.

The observed managed ACL and attachment were absent. Its managed-O digest is
`sha256:b6e03252871711c27e7a4d696a6f5bea8f246788f2536eb7feddb2904396effd`.
The normalized proposed ACL D1 digest is
`sha256:e4b8c5485d87476b4132351f5a9059bd7f9603a5205966834e9220ab70349b0d`.
The observation-bound IOS artifact proposes exactly:

```text
ip access-list extended NCDP-SERVERS-PROTECT-OUT
 10 permit tcp 10.60.10.0 0.0.0.255 10.60.20.0 0.0.0.255 eq 443
 20 deny ip 10.60.10.0 0.0.0.255 10.60.20.0 0.0.0.255
 30 permit ip any any
interface GigabitEthernet3.20
 ip access-group NCDP-SERVERS-PROTECT-OUT out
```

The envelope owns only device 1, interface 22, prefixes 6/7, the Git policy,
and the five accepted ACL fields. It does not own `Gi3.10`, management,
assurance hosts, VLAN switching, OSPF, or another device.

## Differential Batfish assurance

The accepted B4-3 behavioral baseline remains
`sha256:18ba3232b8ec85019b0afcfd7239eb3818e8dc788948482a54ffb2eb430dcda6`.
It is prior assurance evidence, not ACL D0. The secured candidate is
`sha256:afa5422fdd6c230693fda6c7ae05648251fbdc5468f0e5c415b236eb3506be36`.
Only the core candidate gains the exact ACL and outbound attachment.

Pinned PyBatfish `2025.7.7.2423` and Batfish server `2026.07.20.3565` passed
40/40 invariants. Every probe returned exactly one untruncated trace:

| Probe | B4-3 baseline | B4-4 secured | Secured final node/path |
|---|---|---|---|
| USERS → SERVERS TCP/443 | `ACCEPTED` | `ACCEPTED` | `assurance-servers-probe`; through `core-02` |
| USERS → SERVERS TCP/22 | `ACCEPTED` | `DENIED_OUT` | `core-02` |
| USERS → SERVERS ICMP | `ACCEPTED` | `DENIED_OUT` | `core-02` |
| SERVERS → USERS TCP | `ACCEPTED` | `ACCEPTED` | `assurance-users-probe`; through `core-02` |
| USERS gateway | `ACCEPTED` | `ACCEPTED` | `core-02` |
| SERVERS gateway | `ACCEPTED` | `ACCEPTED` | `core-02` |

Allowed paths exclude Junos and transit. Denied paths terminate at core and do
not reach the SERVERS fixture. Batfish also semantically verified the exact
three rules, ordering, effective catchall permit, and sole outbound attachment.

The model remains four managed network devices plus two Batfish-only hosts and
six layer-1 edges. The hosts are not NetBox/CML objects, credentials, managed
targets, or LIVE endpoint claims.

## Preserved boundaries

The routed-underlay, OSPF, and VLAN D1 digests are unchanged. NetBox, CML,
Terraform, OpenBao policy/credentials, host trust, protected authority,
Oxidized, observability, SNMP, and all LIVE configurations are unchanged.
Disposable CML staging, protected delivery, observability runtime validation,
and synthetic SNMPv3 runtime validation remain disabled pending explicit
operator decisions.
