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

Pending the commit-bound one-shot LIVE run. No D0 or real store exists merely
because this implementation is present.

The run will record, for each vertical, both full timestamped observation
evidence digests, canonical D0/O/D1 digests, the generation-one acceptance
evidence and record digests, exact `managed-state:acceptance:<vertical>:<digest>`
identity, D0/O outcome, and D0/D1 proposal outcome. Network-device writes stay
zero. The only intended durable external mutation is the exact four-record
private managed-state store; the two temporary AppRole SecretIDs are retired.
