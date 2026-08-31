# OpenBao secret provider

## Boundary and authentication

OpenBao is the primary personal-lab credential provider. The local/bootstrap
path authenticates with AppRole using `NCDP_OPENBAO_URL`, `NCDP_OPENBAO_ROLE_ID`, and
`NCDP_OPENBAO_SECRET_ID`; it does not accept a bootstrap OpenBao token. RoleID and
SecretID are never CLI arguments or plan/evidence fields. The personal-lab
SecretID is a bounded bootstrap mechanism, not the mature Buildkite identity
design.

Each credential load performs a fresh AppRole login, accepts only a positive
token lease no longer than ten minutes, and uses the issued token for exactly one
authenticated operation. The personal-lab role issues five-minute, single-use
tokens. NCDP does not cache, renew, inspect, or retry tokens and does not place
them in persistent HTTP headers.

The mature Buildkite path uses a Buildkite-issued OIDC JWT with issuer
`https://agent.buildkite.com`, audience `urn:ncdp:openbao:deploy`, and the fixed
OpenBao JWT role `ncdp-buildkite-deploy`. The job requests a 300-second JWT with
`pipeline_id` as its subject claim, making the immutable pipeline UUID available
as standard JWT `sub`. OpenBao binds that exact subject and uses `sub` as the
stable machine `user_claim`, avoiding a new Identity alias for every job. It
constrains the `main` branch and `deploy-gate` step. OpenBao,
not NCDP, verifies the JWT signature and role
constraints. A successful login must map required JSON pointers `/sub` to
`pipeline_id` metadata and `/build_commit`, `/build_branch`, `/step_key`, and
`/job_id` to their corresponding metadata names. NCDP compares all five values
exactly with the validated deployment context and
rejects a token lease over 300 seconds. Thus each changing `job_id` remains
cryptographically bound even though the Identity alias is stable. The bearer JWT
is accepted only through bounded stdin, and neither it nor the resulting OpenBao
token is logged, persisted, cached, or renewed.

Protected-main diagnostics proved that Buildkite correctly populated `sub` with
the immutable pipeline UUID but omitted a separate `pipeline_id` claim. The old
required `/pipeline_id` mapping therefore caused OpenBao to reject login. The
standard subject is now the sole canonical pipeline claim; the application still
receives and exactly verifies metadata named `pipeline_id`.

The active main-only deployment gate implements this exchange after human
authorization and before promotion verification. It rejects ambient AppRole and
direct device credentials, and pipes the JWT without argv, a shell variable, or
a file. A repository operator tool idempotently enables and verifies the `jwt/`
mount, discovery configuration, and exact role using `BAO_TOKEN` only from its
operator environment. An existing mount must have type `jwt` and exact
description `NCDP Buildkite workload identity`; an unmarked mount is not
overwritten. The write explicitly sets `skip_jwks_validation=false`. Read-back
requires the exact discovery URL and issuer and OpenBao validator `status=valid`,
while rejecting alternate JWKS/static keys and OIDC client credentials. The 7B
role issues a one-use token with no default policy, no policies, and TTL limits
no greater than 300 seconds. NCDP additionally rejects a login response with any
effective token or Identity policy, proving the returned capability cannot read
device secrets. Protected-main build #26 externally validated this role and
application boundary in normal hardened mode, including zero effective policy,
without retrieving a device secret or performing a device write.

The operator supplies `NCDP_OPENBAO_URL`, the exact immutable pipeline UUID in
`NCDP_BUILDKITE_PIPELINE_ID`, and the administrative `BAO_TOKEN` environment
value, then runs `uv run python scripts/openbao/configure_buildkite_jwt.py` from
a trusted administrative shell. The tool never accepts the token as an argument
and reports only whether the mount was newly enabled and whether the non-secret
backend, role, and no-device-capability contracts were verified. This is an
operator action, never a Buildkite job action.

Buildkite ephemeral staging uses audience `urn:ncdp:openbao:staging` and
separate roles `ncdp-buildkite-staging-device-1` and `-2`. Each binds the
immutable pipeline subject and exact `cml-staging` step and issues one
five-minute, one-use token with no default policy and only its matching exact
device-read policy. The application verifies mapped pipeline, build, commit,
branch, step, and job identity before the single KV-v2 read. One in-memory JWT
is used for the two independent role logins and discarded. Staging rejects
AppRole; deployment roles, audiences, policies, and approval remain unchanged.
Under ADR 0024 these roles read the same device 1/2 secrets used for live
management. A credential belongs to the logical NetBox device, not its live or
staging management IP; no `.30/.40`-specific secrets exist.

7C-A adds a separate device-specific Buildkite JWT role family without changing
the AppRole provider or accepted zero-policy identity role. Role
`ncdp-buildkite-cml-deploy-device-<id>` carries exactly policy
`ncdp-buildkite-cml-device-<id>-read`, whose sole capability is `read` on
`ncdp/data/devices/<id>/ssh`. A dedicated environment-only operator verifies the
owned mount and unchanged 7B role, writes and reads back the exact policy and
role, and rejects divergent state. The deployment provider verifies exact
identity, lease, token/Identity/aggregate/external policy results and consumes
the single-use token on one exact KV-v2 GET. It does not use AppRole.

## Exact KV-v2 derivation

The provider supports NetBox-backed inventory only. It requires a stable identity
matching `netbox:dcim.device:<positive integer>` and derives the credential path
solely from that ID. Device ID 1 maps as follows:

- logical path: `ncdp/devices/1/ssh`;
- API path: `/v1/ncdp/data/devices/1/ssh`;
- non-secret reference: `openbao:kv-v2:ncdp/devices/1/ssh`.

Hostname, management address, interface, and Git input cannot select another
secret. Normal NCDP operation performs AppRole login and reads the exact KV-v2
path only; it never writes OpenBao data or falls back to environment credentials.

## Immutable non-secret provenance

Secret providers resolve a `credential_source` and `credential_reference` before
loading secret values. Both fields are frozen into `DeploymentPlan`, covered by
its canonical digest, and copied to `ChangeRecord`. Deployment re-resolves and
compares the current reference after inventory verification but before OpenBao
login, credential retrieval, or device connection. A source or reference mismatch
returns `STALE_PLAN`.

Username, password, AppRole IDs, and issued tokens never enter models, plans,
digests, evidence, logs, or normalized errors. Credential values and KV secret
versions are deliberately not plan-bound: trusted administrative rotation at the
same approved reference does not invalidate network configuration intent.

## Transport and limitations

HTTPS uses normal system trust verification. Plain HTTP is permitted only for
exact loopback hostnames (`localhost`, `127.0.0.1`, or `::1`). Userinfo, query,
fragment, and non-root URL paths are rejected. Requests have bounded timeouts,
do not follow redirects, do not inherit environment proxy routing, and have no
retry layer or response-body error exposure. Production proxy support would
require an explicit reviewed design.

The native operator UI is available locally at
`http://127.0.0.1:8200/ui/` through that same loopback-only listener. It does
not add a listener, network exposure, authentication method, or credential.
Sign in with an existing authorized OpenBao authentication method appropriate
to the operator task; the UI does not provide anonymous secret access. Never
create or display a convenience token for a demonstration.

OpenBao access is short-lived and least privilege, but the underlying IOS XE
username/password stored in KV-v2 is static. This increment does not provide
dynamic or short-lived Cisco credentials, per-command Cisco authorization,
rotation, TACACS/RADIUS, or OpenBao Agent. `EnvironmentSecretProvider` remains
an explicit offline/test option.
