# OpenBao secret provider

## Boundary and authentication

OpenBao is the primary personal-lab credential provider. NCDP authenticates with
AppRole using `NCDP_OPENBAO_URL`, `NCDP_OPENBAO_ROLE_ID`, and
`NCDP_OPENBAO_SECRET_ID`; it does not accept a bootstrap OpenBao token. RoleID and
SecretID are never CLI arguments or plan/evidence fields. The personal-lab
SecretID is a bounded bootstrap mechanism, not the mature identity design.
Buildkite JWT/OIDC federation remains future work.

Each credential load performs a fresh AppRole login, accepts only a positive
token lease no longer than ten minutes, and uses the issued token for exactly one
authenticated operation. The personal-lab role issues five-minute, single-use
tokens. NCDP does not cache, renew, inspect, or retry tokens and does not place
them in persistent HTTP headers.

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
do not follow redirects, and have no retry layer or response-body error exposure.

OpenBao access is short-lived and least privilege, but the underlying IOS XE
username/password stored in KV-v2 is static. This increment does not provide
dynamic or short-lived Cisco credentials, per-command Cisco authorization,
rotation, TACACS/RADIUS, OpenBao Agent, or production-grade Buildkite identity
federation. `EnvironmentSecretProvider` remains an explicit offline/test option.
