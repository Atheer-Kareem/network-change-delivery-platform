# ADR 0010: Buildkite/OpenBao JWT workload identity

## Status

Accepted for the Increment 7B-A application foundation; external federation
acceptance is pending.

## Decision

Buildkite is the OIDC issuer and OpenBao is the cryptographic JWT verification
authority. The future deployment job must request its JWT with this exact
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

The future OpenBao role contract is:

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
Buildkite deployment context. The role's issued OpenBao token must use a TTL and
explicit maximum TTL no greater than 300 seconds, require no renewal, and carry
only the narrow policy needed by the eventual deployment secret read. One-use
issuance is preferred where it remains compatible with that exact read flow.

The JWT enters NCDP through a bounded, single-value stdin boundary, never argv.
The OpenBao token lease may not exceed 300 seconds. JWTs and OpenBao tokens are
ephemeral: they are not logged, persisted, modeled, cached, or renewed. NCDP
does not decode JWT claims as identity proof and does not implement signature
verification itself.

AppRole remains available for explicit local, bootstrap, and personal-lab
workflows. Authentication mechanism is not device credential provenance, so
plans retain the existing `openbao` source and KV-v2 reference contract.

## Consequences

7B-A provides a testable application and CLI boundary but does not change the
active Buildkite pipeline, configure external OpenBao, retrieve a device secret,
or perform deployment. A bounded 7B follow-up owns external JWT-role setup and a
real Buildkite OIDC exchange. Increment 7C still owns fully enforced live CML
deployment.
