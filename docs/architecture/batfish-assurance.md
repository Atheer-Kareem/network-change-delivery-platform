# Batfish assurance

Batfish is the offline behavioral-assurance boundary for the exact promoted
network plan. It is not a management-plane reachability, live SNMP polling, or
unmodeled routing-protocol test.

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

Increment 12A makes `batfish-assurance` a visible protected-main stage after
`validation-complete`. ADR 0027 adds a top-level `pr-batfish-assurance` stage
for runtime-relevant pull requests. Both identities reuse the exact same
script, fixed Compose project, and typed assurance boundary. The project is
serialized in `ncdp/batfish-assurance` with limit one, and neither job can be
retried.

On a pull request, Batfish must pass before trusted disposable CML staging can
start. This is cost-aware prevention: offline candidate assurance rejects a
bad modeled behavior before creating the slower vendor runtime. On non-PR
`main`, the PR step is skipped and the protected `batfish-assurance` step still
runs in parallel with CML after the validation barrier. Main regenerates its
own assurance for the exact merged commit and never trusts PR evidence.

The stage verifies the checked-out commit, builds the pinned promotion/assurance
image from that checkout, starts Batfish, performs bounded readiness, executes
`ncdp assure-plan`, and independently runs `ncdp verify-assurance` for successful
evidence. A regular run-scoped `assurance/assurance.json` is uploaded even for a
FAILED/BLOCKED result when safely produced; the original assurance failure
remains authoritative. A strict renderer exposes only typed allowlisted outcome,
identity, digest, flow, differential, and invariant fields in the Buildkite
annotation.

The current policy expects `core-02` and `edge-junos-01` and checks both
directions across their directly connected `/30`:

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

## Assurance-to-promotion handoff

Immutable promotion waits for both CML staging and Batfish assurance. It
downloads `assurance/assurance.json` from the exact `batfish-assurance` step in
the same Buildkite build, rejects an unexpected filesystem shape or symlink,
and independently verifies the exact bytes against the checked-out plan,
policy, and baseline. Promotion then creates and verifies the immutable bundle.
It no longer starts or contacts Batfish.

The similarly named artifact produced by `pr-batfish-assurance` is pre-merge
evidence only. Promotion cannot select it: the download is explicitly scoped to
the protected same-main-build `batfish-assurance` step.
