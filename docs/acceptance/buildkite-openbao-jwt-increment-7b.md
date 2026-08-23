# Increment 7B Buildkite/OpenBao JWT acceptance

Status: application identity foundation and active deployment-gate integration
implemented and locally tested; external acceptance pending.

Increment 7B-A established the repository-owned application boundary. The
main-only deployment gate now requests a Buildkite-issued OIDC JWT and uses that
boundary to authenticate to OpenBao after human authorization. The
implementation validates bounded stdin transport, the fixed JWT role, a maximum
300-second OpenBao lease, and exact OpenBao-mapped pipeline, commit, branch,
step, and job metadata against the current validated Buildkite context. The
external contract requests a separate 300-second Buildkite JWT with the
dedicated audience and immutable `pipeline_id` subject claim. Mocked HTTP adapter
tests cover the login request, failure modes, metadata mismatches, fixed external
constants, and bearer-token secrecy. Static gate contracts prove the exact OIDC
request, pipefail-protected stdin handoff, identity-before-promotion ordering,
and rejection of ambient AppRole and direct device credentials.

The repository operator tool enables `jwt/` only when absent, accepts an existing
mount only when its type and exact NCDP ownership description match, writes the
Buildkite discovery and issuer configuration and exact immutable-pipeline role,
then reads both back and verifies them. It writes
`skip_jwks_validation=false`; because that setting is not returned, read-back
requires the exact discovery URL and issuer plus `status=valid` and rejects
alternate verification sources and OIDC client credentials. Its admin token is
environment-only. Mocked transport tests cover absent, owned, conflicting, and
unowned mounts, exact role constraints, idempotency, malformed responses,
status/redirect/timeout failures, and token redaction.

Protected-main diagnostic execution established the real token shape: Buildkite
set `sub` to the exact immutable pipeline UUID, omitted the separate optional
`pipeline_id` claim, and supplied the expected audience, branch, commit, step,
and job claims. OpenBao returned HTTP 400 with
`claim "pipeline_id" not found in token` because the original role required
`/pipeline_id`. The corrected role uses immutable `sub` as its stable OpenBao
Identity alias and maps `/sub` to application metadata named `pipeline_id`.
`job_id` remains a required mapped claim and exact runtime comparison. The role
has no default policy or other policy, and the application separately requires
the actual login result to contain no token, Identity-derived, or aggregate
effective policy. Successful 7B identity verification therefore grants no
device-secret read even if Identity configuration would otherwise add a policy.

This evidence identifies the interoperability failure but does not claim
federation success. The corrected external OpenBao role still requires
configuration and a successful protected-main exchange. Fix validation uses
only mocked OpenBao HTTP. This increment retrieves no device secret, accesses no
device, and performs no device write. Increment 7B is not complete; Increment 7C
remains responsible for live enforced CML deployment acceptance.
