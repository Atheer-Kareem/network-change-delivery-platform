# Increment 7B Buildkite/OpenBao JWT acceptance

Status: application identity foundation implemented and locally tested;
external acceptance pending.

Increment 7B-A establishes the repository-owned boundary for a future Buildkite
deployment job to authenticate to OpenBao with a Buildkite-issued OIDC JWT. The
implementation validates bounded stdin transport, the fixed JWT role, a maximum
300-second OpenBao lease, and exact OpenBao-mapped pipeline, commit, branch,
step, and job metadata against the current validated Buildkite context. The
future external contract requests a separate 300-second Buildkite JWT with the
dedicated audience and immutable `pipeline_id` subject claim. Mocked HTTP adapter
tests cover the login request, failure modes, metadata mismatches, fixed external
constants, and bearer-token secrecy.

This acceptance is local and does not claim federation success. External
OpenBao JWT configuration and a real Buildkite OIDC exchange are pending. The
active pipeline does not request an OIDC token, and this increment retrieves no
device secret, accesses no device, and performs no device write. Increment 7B
is not complete; Increment 7C remains responsible for live enforced CML
deployment acceptance.
