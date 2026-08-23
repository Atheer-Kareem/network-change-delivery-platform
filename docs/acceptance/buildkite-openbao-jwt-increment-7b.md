# Increment 7B Buildkite/OpenBao JWT acceptance

Status: application identity foundation and active deployment-gate integration
implemented and locally tested; external acceptance pending.

Increment 7B-A established the repository-owned application boundary. The
main-only deployment gate now requests a Buildkite-issued OIDC JWT and uses that
boundary to authenticate to OpenBao after human authorization. The
implementation validates bounded stdin transport, the fixed JWT role, a maximum
300-second OpenBao lease, and exact OpenBao-mapped pipeline, commit, branch,
step, and job metadata against the current validated Buildkite context. The
future external contract requests a separate 300-second Buildkite JWT with the
dedicated audience and immutable `pipeline_id` subject claim. Mocked HTTP adapter
tests cover the login request, failure modes, metadata mismatches, fixed external
constants, and bearer-token secrecy. Static gate contracts prove the exact OIDC
request, pipefail-protected stdin handoff, identity-before-promotion ordering,
and rejection of ambient AppRole and direct device credentials.

The repository operator tool enables `jwt/` only when absent, rejects a
conflicting mount, writes the Buildkite discovery and issuer configuration and
exact immutable-pipeline role, then reads both back and verifies them. Its admin
token is environment-only. Mocked transport tests cover absent, existing, and
conflicting mounts, exact role constraints, idempotency, malformed responses,
status/redirect/timeout failures, and token redaction. The 7B role has no
default policy or other policy, so successful identity verification grants no
device-secret read.

This acceptance is local and does not claim federation success. External
OpenBao JWT configuration and a real protected-main Buildkite OIDC exchange are
pending. Local tests use only mocked OpenBao HTTP. This increment retrieves no
device secret, accesses no device, and performs no device write. Increment 7B is
not complete; Increment 7C remains responsible for live enforced CML deployment
acceptance.
