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
as both `sub` and an explicit claim. OpenBao binds that exact subject, uses
`job_id` as the role's machine `user_claim`, and constrains the `main` branch and
`deploy-gate` step. OpenBao, not NCDP, verifies the JWT signature and role
constraints. A successful login must return required JSON-pointer mappings for
`pipeline_id`, `build_commit`, `build_branch`, `step_key`, and `job_id` metadata;
NCDP compares all five values exactly with the validated deployment context and
rejects a token lease over 300 seconds. The bearer JWT is accepted only through
bounded stdin, and neither it nor the resulting OpenBao token is logged,
persisted, cached, or renewed.

Increment 7B-A implements and tests this application boundary with mocked HTTP.
The active Buildkite pipeline does not yet request an OIDC token or contact
OpenBao; external role configuration and federation acceptance remain pending.

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

OpenBao access is short-lived and least privilege, but the underlying IOS XE
username/password stored in KV-v2 is static. This increment does not provide
dynamic or short-lived Cisco credentials, per-command Cisco authorization,
rotation, TACACS/RADIUS, or OpenBao Agent. `EnvironmentSecretProvider` remains
an explicit offline/test option.
