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
