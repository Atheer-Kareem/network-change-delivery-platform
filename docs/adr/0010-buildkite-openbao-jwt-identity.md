# ADR 0010: Buildkite/OpenBao JWT workload identity

## Status

Accepted and implemented for Increment 7B integration; external federation
configuration and protected-main acceptance are pending.

## Decision

Buildkite is the OIDC issuer and OpenBao is the cryptographic JWT verification
authority. The deployment gate requests its JWT with this exact
contract:

```bash
buildkite-agent oidc request-token \
  --audience urn:ncdp:openbao:deploy \
  --lifetime 300 \
  --subject-claim pipeline_id
```

`pipeline_id` is not a default Buildkite OIDC claim. Selecting it as the subject
claim both sets `sub` to the immutable pipeline UUID and includes the
`pipeline_id` claim for mapping and application comparison. The 300-second
Buildkite JWT lifetime is distinct from the OpenBao token lease limit.

The OpenBao role contract is:

- role name: `ncdp-buildkite-deploy`;
- `role_type = jwt`;
- issuer/discovery authority: `https://agent.buildkite.com`;
- `bound_audiences = ["urn:ncdp:openbao:deploy"]`;
- `bound_subject` is the exact configured immutable NCDP Buildkite pipeline UUID;
- `user_claim = job_id`;
- exact bound claims are `build_branch = main` and `step_key = deploy-gate`;
- required claim mappings are `/pipeline_id` → `pipeline_id`, `/build_commit` →
  `build_commit`, `/build_branch` → `build_branch`, `/step_key` → `step_key`,
  and `/job_id` → `job_id`.

The leading `/` JSON-pointer mapping form makes those source claims required.
NCDP compares all five OpenBao-verified values exactly with its validated
Buildkite deployment context. For 7B identity acceptance, the role's issued
OpenBao token has no default policy, no policies, TTL, maximum TTL, and explicit
maximum TTL of at most 300 seconds, and one permitted use. It therefore has no
device-secret capability. A later reviewed 7C decision must attach any exact
secret-read policy needed by live deployment.

The JWT enters NCDP through a bounded, single-value stdin boundary, never argv.
The OpenBao token lease may not exceed 300 seconds. JWTs and OpenBao tokens are
ephemeral: they are not logged, persisted, modeled, cached, or renewed. NCDP
does not decode JWT claims as identity proof and does not implement signature
verification itself.

AppRole remains available for explicit local, bootstrap, and personal-lab
workflows. Authentication mechanism is not device credential provenance, so
plans retain the existing `openbao` source and KV-v2 reference contract.

## Consequences

The application boundary, serialized deployment-gate integration, and
idempotent operator configuration tool are implemented. The deployment job
rejects legacy AppRole and direct device credentials, pipes the JWT directly
from Buildkite to NCDP, and cannot report final authorization success until
OpenBao-verified identity and the existing promotion checks both pass. External
JWT-role configuration and a real protected-main exchange remain pending and
are not established by local tests. No device secret is retrieved and no
deployment is performed. Increment 7C still owns fully enforced live CML
deployment.
