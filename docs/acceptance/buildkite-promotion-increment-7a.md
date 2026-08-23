# Increment 7A acceptance

Increment 7A is complete, including external protected-main acceptance in
Buildkite build #11 for merged commit
`8bb377958cd01c387503b1b11c80a13c4d6ae806`.

The accepted workflow proves:

- protected GitHub `main` and GitHub-to-Buildkite triggering;
- validation-only pull requests with visible containerized quality checks;
- main-only promotion routed through `ncdp-validation` and serialized by
  `ncdp/batfish-promotion`;
- successful Batfish readiness and PASSED exact plan-bound assurance;
- one immutable promotion artifact bound to the exact commit, plan, policy,
  baseline, and assurance record;
- explicit human entry of the exact plan, assurance, and promotion digests;
- deployment-gate routing through `ncdp-deploy` and serialization by
  `ncdp/network-change-deployment`;
- repository-owned verification of the downloaded promotion artifact, commit,
  and exact approval values; and
- successful authorization with zero device writes.

Approval values are block-step build meta-data, not environment variables.
The repository-owned gate validates Buildkite context and compares the exact
untrimmed values before reporting authorization readiness.

For build #11 the promotion step displayed, and the human approver entered:

- Plan digest: `sha256:02a3bece7cc1f67ae77e4f3cd436d1366489fa63fddf7b3b442f7115866086f4`
- Assurance record digest: `sha256:2a0c364bdc1242fb5a884cf363a70066055bfb95ca75b71683493b428a0f9efa`
- Promotion digest: `sha256:1aa67a996e09ae8a7ab4024a4060991bbfa84ed5c4d0867e81e6cca26a869e4e`

The gate downloaded the exact artifact set from the promotion step, verified
the accepted commit and all three values, reported
`deployment authorization gate: PASSED`, and reported
`device write executed: NO`.

7A does not make Buildkite metadata cryptographic workload identity. It does not
provide OIDC/OpenBao JWT federation, deployment secret retrieval, an actual
device write from Buildkite, or live CML deployment through Buildkite. Identity
federation remains 7B; fully enforced live CML deployment acceptance remains 7C.

Build #11's manually entered digest workflow remains the historical acceptance
record. The active workflow was later refined to fieldless human authorization
with machine-recorded promoted digests and independent gate verification. That
new click-only UX requires its own later protected-main exercise and is not
claimed as externally accepted by this documentation update.
