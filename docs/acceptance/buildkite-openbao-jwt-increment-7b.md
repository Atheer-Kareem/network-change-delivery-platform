# Increment 7B Buildkite/OpenBao JWT acceptance

Status: complete, including protected-main external federation acceptance.

## Accepted protected-main result

Buildkite build #26 accepted exact protected-main commit
`e35ecd6dd077948e0b279536968241b8fbfa6113`. GitHub and Buildkite reported the
combined status as successful. Normal hardened mode, not the optional diagnostic
mode, performed the real chain:

```text
Buildkite OIDC token issuance
→ OpenBao JWT signature, issuer, audience, and role validation
→ immutable pipeline identity in JWT sub
→ OpenBao /sub → pipeline_id metadata mapping
→ NCDP exact runtime identity comparison
→ zero-effective-policy verification
→ exact promotion verification
→ authorization PASS
→ NO device write
```

The final gate reported:

```text
commit: e35ecd6dd077948e0b279536968241b8fbfa6113
plan digest: sha256:02a3bece7cc1f67ae77e4f3cd436d1366489fa63fddf7b3b442f7115866086f4
assurance digest: sha256:b0fae84974a7cdc341dec5f99942b0b2117136dfafeb3ed576aa4389a5d07358
promotion digest: sha256:3b8e77a4ac4119b976ca859ac82dccb45ce5e85ecd5630ee01ae1befd986607d
deployment authorization gate: PASSED
device write executed: NO
```

The active token request remained:

```bash
buildkite-agent oidc request-token \
  --audience urn:ncdp:openbao:deploy \
  --lifetime 300 \
  --subject-claim pipeline_id
```

The accepted OpenBao role bound the exact immutable pipeline UUID as
`bound_subject`, used `user_claim = sub`, and required `/sub` → `pipeline_id`,
`/build_commit` → `build_commit`, `/build_branch` → `build_branch`, `/step_key` →
`step_key`, and `/job_id` → `job_id`. NCDP then required the mapped
`pipeline_id` to equal `BUILDKITE_PIPELINE_ID` and compared commit, branch, step,
and job metadata exactly.

## Troubleshooting progression retained

The first real exchange reached OpenBao but failed because the role required
`/pipeline_id` while the live token omitted that duplicate optional claim. A
bounded protected-main diagnostic showed `alg = RS256`, the correct issuer,
subject, audience, branch, commit, step, and job, and `pipeline_id = null`.
OpenBao returned HTTP 400 with `claim "pipeline_id" not found in token`.

The architecture was corrected to use standard JWT `sub` as the canonical
pipeline identity and map it to application metadata named `pipeline_id`. The
deterministic operator migrated the existing NCDP-owned role and verified exact
read-back. Build #26 then passed the real federation path. The opt-in
`NCDP_OPENBAO_JWT_DIAGNOSTICS=1` facility remains available for bounded
troubleshooting but is not part of normal authorization.

## Security acceptance

- Real Buildkite OIDC JWT requested: **YES**.
- Real OpenBao JWT authentication: **YES**.
- OpenBao signature validation: **YES**.
- Issuer, audience, pipeline, branch, and step constraints enforced: **YES**.
- Runtime pipeline, commit, branch, step, and job comparison: **YES**.
- OpenBao token lease no greater than 300 seconds: **YES**.
- Zero effective token, Identity-derived, and aggregate policies verified:
  **YES**.
- Device-secret retrieval: **NO**.
- NetBox access: **NO**.
- CML or device access: **NO**.
- Device writes: **NO**.
- Increment 7B complete: **YES**.
- Increment 7C started: **NO**.

This personal-lab acceptance does not claim production-grade host isolation,
fleet-wide atomicity, secret retrieval, or deployment execution. Increment 7C
remains responsible for fully enforced live CML deployment acceptance.
