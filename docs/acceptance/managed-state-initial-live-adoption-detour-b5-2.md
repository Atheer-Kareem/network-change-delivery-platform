# Detour B5-2 initial LIVE managed-state adoption

Date: 2026-09-01

B5-2 is the first explicit initialization of real accepted D0. The committed
operator workflow performs two independent, credential-bounded read-only LIVE
passes around a four-vertical staged append-only initialization. It refuses an
existing final store, a dirty or mismatched source checkout, any change from
the last accepted B4 observations, a partial generation-one store, or any
second-pass D0/O mismatch.

The implementation commit used as the acceptance source, selected private
store root, and exact secret-free observation/evidence/state/record results are
recorded here only after the one-shot run succeeds. The implementation commit
is not amended after adoption.

## Pre-adoption continuity expectation

These canonical digests reconstruct the last accepted B4 observations. They
are a continuity gate only, not D0 or accepted-state references.

| Vertical | Prior B4 observation digest |
| --- | --- |
| routed_underlay | `sha256:6951568295ee0d1c1ff118ce68fd1324ade2a241a3d85049c82c83eaa1543c40` |
| ospf | `sha256:99f0e0bd53255faf9deb57984edabb7ca49c42bfeb487ee31a3bf3cdee9f4684` |
| vlan | `sha256:3c244903ad393c1647a2818473400bb14ed4bdcd92ff694d5492bd791af6aa54` |
| acl | `sha256:388138ae96e36bb5e5ba3e5c7fdd387986950993598857bdf63040a0391b2dea` |

## Real acceptance result

The exact adoption source commit was
`216390ea8d051e331de55ca1efadcde0a6b4f5ab`. The final implementation commit
was pushed and the checkout was clean at that exact HEAD before the live run.
The selected explicit store root was
`/Users/netdevops/.local/share/ncdp/managed-state`, beneath the existing private
operator-data convention. It was absent before initialization. The promoted
root and managed directories are mode `0700`; its exact four canonical record
files are mode `0600`. There is no `current.json` or mutable head pointer.

| Vertical | First full O evidence | Canonical D0 | Acceptance evidence | Generation-one record |
| --- | --- | --- | --- | --- |
| routed_underlay | `sha256:75fb9d41959226af5a26496e242b582fdc3ff4902fcac409cd2a296195d9f78a` | `sha256:6951568295ee0d1c1ff118ce68fd1324ade2a241a3d85049c82c83eaa1543c40` | `sha256:612a8de72e97a452f5faff5dc9d735be671eb47c8ae923a1afb1044aa6b988c7` | `sha256:ec66865f6ff0b6586c6d5f8526e5ca37385a59bf0aac6950db484817e3b3461a` |
| ospf | `sha256:e526e2f685e6e4c98e6f8f2ceadb72ce66214e54aa4b5c2fc931e07ba3e8d718` | `sha256:99f0e0bd53255faf9deb57984edabb7ca49c42bfeb487ee31a3bf3cdee9f4684` | `sha256:c864dc827163b0c1132310ea1933afd8e9875b3b04c060a990280d5a2d53e11f` | `sha256:34d575f68125efccd6cbfad23d1ef980289b6bdfdba7c567e14e5ed1921e6418` |
| vlan | `sha256:eca8091881a41af76f4df977aca67cb84f06dd9f14c6e387de287afaea0ef8b7` | `sha256:3c244903ad393c1647a2818473400bb14ed4bdcd92ff694d5492bd791af6aa54` | `sha256:a07ad5f5d0b9ca23a39adc09e47308da6a83a76f600029404bcaf3b0f68fd380` | `sha256:0ede0553403a0f112a8a814c99ed0421a574d27f4cef1f3171baf67a905a439c` |
| acl | `sha256:d8ccefd35ce51e20b1867a1c762c9fcc32e43c393f4097199082de619149dac2` | `sha256:388138ae96e36bb5e5ba3e5c7fdd387986950993598857bdf63040a0391b2dea` | `sha256:882e185fb59f32a4fb6e697877324bf54e7fe8116a6dc3294cdb0db1d0ef8b71` | `sha256:b4e2c0c780473669f58bb3cf3599b8b94183bc76940a40cbeffac3a9812f8cda` |

Accepted references are exactly:

- `managed-state:acceptance:routed_underlay:sha256:612a8de72e97a452f5faff5dc9d735be671eb47c8ae923a1afb1044aa6b988c7`
- `managed-state:acceptance:ospf:sha256:c864dc827163b0c1132310ea1933afd8e9875b3b04c060a990280d5a2d53e11f`
- `managed-state:acceptance:vlan:sha256:a07ad5f5d0b9ca23a39adc09e47308da6a83a76f600029404bcaf3b0f68fd380`
- `managed-state:acceptance:acl:sha256:882e185fb59f32a4fb6e697877324bf54e7fe8116a6dc3294cdb0db1d0ef8b71`

| Vertical | Second full O evidence | Second canonical O | D0/O | Canonical Git D1 | D0/D1 |
| --- | --- | --- | --- | --- | --- |
| routed_underlay | `sha256:eb0e00161532f4b7a3f32028a2638c2e895a2ad90669363afeaaf2a7c41934f8` | `sha256:6951568295ee0d1c1ff118ce68fd1324ade2a241a3d85049c82c83eaa1543c40` | `IN_SYNC` | `sha256:f610b0aae6d3e27d52823ef6740e67dfc3078592c4a244346dd31259732bb2f0` | `CHANGE_PROPOSED` |
| ospf | `sha256:0df2177c08a10ec8d6ebee5df54ee4dbce792e0b03cbfc94aa4481088090fb1a` | `sha256:99f0e0bd53255faf9deb57984edabb7ca49c42bfeb487ee31a3bf3cdee9f4684` | `IN_SYNC` | `sha256:22d403c2899738ce4a192bc702bd5e485f6b9ac97f5a0bb586603b9f6efc0d16` | `CHANGE_PROPOSED` |
| vlan | `sha256:c1735b4b7eb5580e5df4e71a9226160bd6bc0bd89708c88dd76ee28bf3341849` | `sha256:3c244903ad393c1647a2818473400bb14ed4bdcd92ff694d5492bd791af6aa54` | `IN_SYNC` | `sha256:4df7b44ebca3b62109dbb6a74f074ba83627b6b235eb932edb53f082396ae19e` | `CHANGE_PROPOSED` |
| acl | `sha256:7367936424310645a93e5487b198d066d90d8ae60abccd9b1cab44e5be06bdc1` | `sha256:388138ae96e36bb5e5ba3e5c7fdd387986950993598857bdf63040a0391b2dea` | `IN_SYNC` | `sha256:88720b02bf3a2fc5d95aa155e8408bd992ea08d1123ac3a992c5404219efd946` | `CHANGE_PROPOSED` |

Every chain has generation `1`, mode `INITIAL_ADOPTION`, no predecessor, no
post-write convergence proof, and `device_writes = 0`. The accepted run used
two distinct bounded personal-lab AppRole SecretIDs and retired both. A prior
diagnostic pass exposed provider-order coupling in the routed-underlay
projection and stopped before staging; that diagnostic SecretID was also
retired. The corrected projection orders by stable interface identity without
changing any canonical D1 or continuity digest.

B5-2 created real D0 for the first time. The LIVE semantics remain the accepted
B4 observations: legacy core/Junos `10.6.12.0/30`, absent OSPF, absent VLAN
router-on-a-stick service, and absent managed ACL. Current Git B4 intent remains
proposed D1. No network-device write or NetBox, CML, Terraform, host-trust,
OpenBao policy, stored-credential, or protected-authority mutation occurred.
