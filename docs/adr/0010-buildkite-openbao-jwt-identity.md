# ADR 0010: Buildkite/OpenBao JWT workload identity

## Status

Accepted and externally validated; Increment 7B complete.

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

Selecting `pipeline_id` as the subject claim sets standard JWT `sub` to the
immutable pipeline UUID. Protected-main evidence showed that it does not
necessarily add a separate `pipeline_id` claim: `sub` held the correct UUID while
`pipeline_id` was absent. The role therefore treats `sub` as the canonical
pipeline identity and does not depend on a duplicate optional claim. The
300-second Buildkite JWT lifetime is distinct from the OpenBao token lease limit.

The OpenBao role contract is:

- role name: `ncdp-buildkite-deploy`;
- `role_type = jwt`;
- issuer/discovery authority: `https://agent.buildkite.com`;
- `bound_audiences = ["urn:ncdp:openbao:deploy"]`;
- `bound_subject` is the exact configured immutable NCDP Buildkite pipeline UUID;
- `user_claim = sub`, providing one stable Identity alias for the
  immutable workload rather than a new alias for every job;
- exact bound claims are `build_branch = main` and `step_key = deploy-gate`;
- required claim mappings are `/sub` → `pipeline_id`, `/build_commit` →
  `build_commit`, `/build_branch` → `build_branch`, `/step_key` → `step_key`,
  and `/job_id` → `job_id`.

The leading `/` JSON-pointer mapping form makes those source claims required.
OpenBao returns the subject under the application-facing metadata name
`pipeline_id`. `job_id` remains mapped and NCDP compares all five
OpenBao-verified values exactly with its validated Buildkite deployment context,
so stable pipeline identity does not weaken per-job binding. For 7B identity
acceptance, the role's
issued OpenBao token has no default policy, no policies, TTL, maximum TTL, and
explicit maximum TTL of at most 300 seconds, and one permitted use. NCDP also
requires the actual login result's token, Identity-derived, and aggregate policy
lists to be absent, null, or empty. It therefore fails closed if Identity adds
capability despite the role configuration. A later reviewed 7C decision must
attach any exact secret-read policy needed by live deployment.

The operator explicitly writes `skip_jwks_validation = false`, so backend
configuration fails if the issuer validator cannot be built. Because OpenBao
does not expose that write-only safeguard on config reads, read-back instead
requires the exact discovery URL and issuer plus `status = valid`, rejects any
exposed JWKS or static-key source, and rejects OIDC client credentials. The
mount-wide configuration is changed only when `jwt/` has both type `jwt` and the
exact ownership description `NCDP Buildkite workload identity`; another or
unmarked JWT mount fails closed.

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
OpenBao-verified identity and the existing promotion checks both pass. A real
protected-main diagnostic exposed the obsolete `/pipeline_id` mapping:
Buildkite emitted the correct immutable UUID in `sub`, omitted the separate
`pipeline_id` claim, and OpenBao rejected login with
`claim "pipeline_id" not found in token`. The corrected role maps `/sub`.
After the deterministic operator migrated the owned role, protected-main
Buildkite build #26 completed real Buildkite OIDC issuance, OpenBao validation,
`/sub` mapping, exact NCDP runtime comparison, zero-policy verification, and
promotion authorization for commit
`e35ecd6dd077948e0b279536968241b8fbfa6113`. The gate passed without retrieving
a device secret or performing a device write. This completes Increment 7B;
Increment 7C still owns fully enforced live CML deployment.
