# Managed state and drift

Detour B5-1 establishes the durable D0 contract without creating a real D0.
The four B4 service states remain proposals: they have not been applied to LIVE
and must not be relabeled as accepted state.

## Canonical managed-state projection

Each supported vertical has explicit observation and desired-state projection
functions. They produce a typed `ManagedStateSnapshot` containing schema
version, vertical, the exact `ManagedOwnershipEnvelope`, a normalized managed
payload, and an intrinsic canonical-JSON digest. Timestamps and provider text
are excluded. The envelope is included in the digest, so identical values under
different ownership cannot compare equal.

The projections cover exactly `routed_underlay`, `ospf`, `vlan`, and `acl`.
They do not form an arbitrary configuration tree or plugin registry. Their core
contract is:

```text
managed projection of O == managed projection of D1
```

when observation and desired state are semantically equal inside the envelope.
Collision and ambiguity facts remain observation-admission safeguards, but
unowned facts such as interface operational status, provider-local OSPF process
identity, non-service native VLAN, and unrelated reserved ACL metadata do not
enter the managed digest.

The current Git proposals have separate B5 canonical D1 digests:

| Vertical | Canonical managed D1 digest |
| --- | --- |
| routed_underlay | `sha256:f610b0aae6d3e27d52823ef6740e67dfc3078592c4a244346dd31259732bb2f0` |
| ospf | `sha256:22d403c2899738ce4a192bc702bd5e485f6b9ac97f5a0bb586603b9f6efc0d16` |
| vlan | `sha256:4df7b44ebca3b62109dbb6a74f074ba83627b6b235eb932edb53f082396ae19e` |
| acl | `sha256:88720b02bf3a2fc5d95aa155e8408bd992ea08d1123ac3a992c5404219efd946` |

These do not replace the established B4 service-subject digests.

## Append-only acceptance

`ManagedStateAcceptanceEvidence` records an explicit acceptance mode, UTC
time, vertical, exact envelope, complete canonical state and digest, exact
40-hex source commit, source observation/evidence digest, optional exact prior
accepted-state reference, and its own intrinsic digest. The only modes are:

- `INITIAL_ADOPTION`: an operator explicitly accepts fresh observed managed
  reality as generation 1;
- `POST_WRITE_VALIDATED`: independent O' has matched reviewed D1 and advances
  an existing exact head.

There is no accept-drift, auto-heal, force, emergency-adoption, or baseline-sync
API.

The derived v1 `AcceptedManagedStateRef` carries the same envelope, canonical
state digest, and source commit. Its evidence reference is exactly:

```text
managed-state:acceptance:<vertical>:<evidence-digest>
```

Each vertical has an independent immutable record chain. Generation 1 is
initial adoption with no predecessor. Later generations are post-write
validated and bind both the prior record digest and prior accepted-state
reference. Content-addressed canonical files are published atomically beneath
a private store outside the checkout. Complete bounded scans reject gaps,
forks, duplicate generations, broken links, corrupt digests, unsafe paths,
symlinks, non-private metadata, unexpected filenames, or noncanonical JSON.
There is deliberately no mutable `current.json`; the validated unique chain
head is current D0.

## Comparison semantics

| Relation | Meaning | Outcome |
| --- | --- | --- |
| `D0 == O` | current reality matches accepted state | `IN_SYNC` |
| `D0 != O` | out-of-band managed change | `DRIFT_DETECTED`, zero writes |
| `D0 == D1` | proposal is a managed no-op | `NO_CHANGE` |
| `D0 != D1` | reviewed change is proposed, not drift | `CHANGE_PROPOSED` |
| `O' == D1` | post-write convergence proven | `CONVERGED` |
| `O' != D1` | post-validation failed; do not advance D0 | `POST_VALIDATION_FAILED` |

All comparisons require the same vertical and exact ownership envelope. Drift
detection is pure and never updates D0.

## Deferred initial adoption

B5-1 creates no operator store and persists no real state. B5-2 will fresh-read
all four LIVE verticals, explicitly initial-adopt current managed reality,
resolve each generation-1 chain independently, fresh-read again, and prove
O equals D0. Only then will current Git B4 intent be compared as proposed D1.
