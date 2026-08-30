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

## First-class protected Buildkite stage

Increment 12A makes `batfish-assurance` a visible protected-main stage after
`validation-complete`. It can run in parallel with disposable CML staging. The
fixed Compose project is serialized in `ncdp/batfish-assurance` with limit one,
and the job cannot be retried.

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

## Assurance-to-promotion handoff

Immutable promotion waits for both CML staging and Batfish assurance. It
downloads `assurance/assurance.json` from the exact `batfish-assurance` step in
the same Buildkite build, rejects an unexpected filesystem shape or symlink,
and independently verifies the exact bytes against the checked-out plan,
policy, and baseline. Promotion then creates and verifies the immutable bundle.
It no longer starts or contacts Batfish.
