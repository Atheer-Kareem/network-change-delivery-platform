# ADR 0010: Buildkite/OpenBao JWT workload identity

## Status

Accepted for the Increment 7B-A application foundation; external federation
acceptance is pending.

## Decision

Buildkite is the OIDC issuer and OpenBao is the cryptographic JWT verification
authority. Deployment jobs will request a short-lived JWT from
`https://agent.buildkite.com` for audience `urn:ncdp:openbao:deploy` and submit
it to the fixed OpenBao JWT role `ncdp-buildkite-deploy`. The role must bind the
immutable pipeline ID, `main` branch, `deploy-gate` step, issuer, and audience.
OpenBao claim mappings must return `pipeline_id`, `build_commit`,
`build_branch`, `step_key`, and `job_id`; NCDP compares those verified values
exactly with its validated Buildkite deployment context.

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
