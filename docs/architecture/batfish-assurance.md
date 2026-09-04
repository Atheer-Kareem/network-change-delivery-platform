# Batfish assurance

Batfish provides the active offline behavioral-assurance boundary for the
profiled PR candidate. Historical schema-v1 plan assurance remains parseable,
but its protected runtime is retired. Batfish is not a management-plane
reachability, live SNMP polling, or unmodeled routing-protocol test.

## Foundation and model boundary

Increment 6A established provider normalization: a snapshot contains only
`configs/` files; Python validates and hashes the snapshot, sends frozen bytes
to the explicit Batfish provider, normalizes observations, and applies typed
policy. Raw Batfish objects never enter platform evidence.

Increment 6B binds the exact validated plan, policy, frozen baseline bytes,
derived candidate, baseline/candidate snapshot digests, expected nodes,
critical flows, invariants, and a self-digested assurance record. Source
snapshots are read once into private mode-0700 staging trees. Each analysis uses
a random Batfish namespace with unique baseline/candidate names.

The committed service is `batfish/batfish:test-2026.07.20.3565` with immutable
multi-platform index
`sha256:feaf749617d92a1ea5f95f54697d878ddb1c902a5bb515f1bb1741b516360966`.
The resolved local arm64 child is
`sha256:0c2ea3fc2f90cac6b9339936da435ac9916d0ad3308bebbe5df13b1a0cf49819`.
PyBatfish is pinned to `2025.7.7.2423`; the server reports
`2026.07.20.3565`. Unit tests use injected providers and do not require Docker.

## First-class Buildkite stages

ADR 0027 adds a top-level `pr-batfish-assurance` stage for runtime-relevant pull
requests. Active PR assurance evaluates the current profiled four-device
candidate through `profiled_pr_batfish_assurance.sh`, retains serialized
concurrency, and prohibits automatic or manual retry. The former protected-main
schema-v1 stage is retired.

On a pull request, active Batfish assurance is prevention evidence for the
reviewed profiled candidate. No disposable CML or protected-delivery branch
follows it.

The profiled PR stage verifies the checked-out commit, builds the pinned
assurance image, starts Batfish, performs bounded readiness, evaluates the
explicit service stack, verifies its typed record, and publishes
`assurance/profiled-pr-assurance.json`. Its annotation shows the four-device
architecture, service stack, exact nodes, D1/candidate digests, and invariant
count without live or credential-bearing data. Historical `ncdp assure-plan`/
`ncdp verify-assurance` artifacts retain their verification meaning but are not
promotion inputs.

The preserved legacy protected policy expects `core-02` and `edge-junos-01` and
checks both directions across their directly connected `/30`:

- `core-02`, `10.6.12.1` → `10.6.12.2`;
- `edge-junos-01`, `10.6.12.2` → `10.6.12.1`.

It also requires no differential reachability. It does not claim to validate
Mac-to-management reachability, SNMP VACM/polling, or nonexistent protocol
adjacencies.

Candidate derivation remains part of `ncdp assure-plan`. The record already
binds the plan, policy, frozen baseline, derived candidate, baseline/candidate
digests, flows, invariants, and its own digest. A separate candidate-generation
artifact would add a handoff without a new safety property and is deliberately
not introduced.

Batfish is complementary to CML rather than a substitute for it. Batfish proves
offline normalized behavior of the derived candidate. CML proves topology,
Day-0, real IOS XE/Junos readiness, strict trust, and the read-only NCDP vendor
paths; CML does not apply or validate the proposed candidate configuration.

## B4-1 routed-underlay candidate assurance

B4-1 adds a separate candidate-only assurance contract for the proposed
four-device routed underlay. It does not alter the legacy v1 plan-bound policy
or Buildkite pipeline. The candidate is generated from normalized D1, not from
PR-supplied CLI or the O-to-D1 vendor change artifacts. The final-state
candidate contains no legacy `10.6.12.0/30` address and contains exactly:

- `core-02` with `10.60.0.1/30` and `10.60.0.5/30`;
- `edge-junos-01` with `10.60.0.2/30` and `10.60.0.9/30`;
- `transit-ios-01` with `10.60.0.6/30` and `10.60.0.10/30`; and
- `access-sw-01` as a recognized node with no routed-underlay prefix.

The typed evaluator requires all four files to parse, exact-four node
recognition, zero initialization issues, exact-six interface-prefix facts,
exactly two participants on each `/30`, and successful direct-neighbor flows
from core to Junos, core to transit, and Junos to transit. It separately
requires no management address and no OSPF process. Directly connected
reachability succeeded without a separate layer-1 snapshot file; Batfish used
the exact interface/prefix candidate derived from the accepted link authority.

The pinned local run passed on PyBatfish `2025.7.7.2423` and Batfish server
`2026.07.20.3565`. The
[B4-1 acceptance record](../acceptance/routed-underlay-detour-b4-1.md) binds the
candidate snapshot and proposed D1 digests. This is proposal evidence only and
is not accepted D0 or permission to write devices.

## B4-1A profiled PR handoff

B4-1A makes the B4-1 final-state candidate the active PR assurance subject.
The exact B3-5 accepted allocation is reconstructed offline from its reviewed
stable-identity catalogs and checked against its accepted digest. Candidate
population/profile selection comes from `PROFILED_POPULATION_CATALOG`, not a
live `ProfiledInventoryPopulation`. No normal NetBox provider, credential
provider, CML client, host trust, or device adapter is available to the new PR
entry point.

`ProfiledPrAssuranceEvidence` requires the exact four nodes and current explicit
`routed_underlay` service stack. It preserves the accepted B4-1 D1 and candidate
digests and all ten invariants. A two-node, missing-member, or extra-node result
cannot pass. See the
[B4-1A acceptance record](../acceptance/profiled-pr-batfish-handoff-detour-b4-1a.md).

## B4-2 composed OSPF assurance

The canonical profiled PR stack is now exactly `routed_underlay, ospf`, with an
independent normalized digest for each subject. The combined final-state
snapshot requires exact four nodes, three OSPF routers/router IDs, six area-0
point-to-point interfaces, three unordered adjacency pairs, three required
remote OSPF routes, and representative remote reachability. `access-sw-01` and
all management interfaces remain excluded.

B4-1 standalone assurance remains 10/10 including `ospf_absent`; that isolation
contract is not weakened when B4-2 composes the service stack. See the
[B4-2 acceptance record](../acceptance/ospf-triangle-detour-b4-2.md).

## B4-3 composed VLAN assurance

The canonical profiled PR stack is now exactly `routed_underlay, ospf, vlan`.
The managed network population remains the four profiled devices. B4-3 alone
adds two Batfish host fixtures under `hosts/`, plus two synthetic host
attachment edges alongside the four accepted infrastructure edges.

The initial attempt originated packets at `@enter(access-sw-01[Gi0/2|Gi0/3])`.
Pinned Batfish returned `NO_ROUTE` because the source was an L2-only network
node with no modeled endpoint forwarding context. This was a modeling-boundary
finding, not a VLAN candidate failure. Exact host models now provide the L3
origins required to prove both gateways and bidirectional pre-ACL inter-VLAN
routing through `core-02`, while Junos and transit are forbidden by evidence
from that path.

The bounded snapshot surface admits only `configs/*`, the one exact
`batfish/layer1_topology.json`, and the two named host JSON files. Historical
B4-1/B4-2 snapshot bytes and digests remain unchanged. See the
[B4-3 acceptance record](../acceptance/vlan-service-detour-b4-3.md).

## B4-4 differential ACL assurance

The canonical profiled PR stack is now exactly `routed_underlay, ospf, vlan,
acl`. B4-4 preserves the accepted B4-3 candidate as a behavioral baseline and
compares the same packet headers with a secured candidate containing one exact
outbound IOS-XE ACL on core `GigabitEthernet3.20`. The baseline is prior
assurance evidence, not ACL D0.

Semantic filter/interface questions prove the exact rules, order, catchall
permit, attachment, and direction. All-trace probes prove USERS HTTPS remains
accepted, USERS SSH and ICMP terminate `DENIED_OUT` at core, reverse traffic
remains accepted, and both gateways remain reachable. Shared underlay, OSPF,
VLAN, managed-node, assurance-host, and layer-1 invariants must also pass. See
the [B4-4 acceptance record](../acceptance/acl-security-detour-b4-4.md).

## Historical assurance-to-promotion handoff

The retired legacy immutable promotion waited for both CML staging and legacy
Batfish assurance. It downloaded
`assurance/assurance.json` from the exact `batfish-assurance` step in the same
Buildkite build, rejects an unexpected filesystem shape or symlink, and
independently verifies the exact bytes against the checked-out plan, policy,
and baseline. Promotion then created and verified the immutable bundle.

The similarly named artifact produced by `pr-batfish-assurance` is pre-merge
evidence only. No current promotion or device-write step consumes it.
