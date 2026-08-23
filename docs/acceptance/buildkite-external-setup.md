# Buildkite external acceptance

This document records the external Buildkite and GitHub acceptance for Increment 7.

PR-side external acceptance is verified. GitHub pull requests trigger Buildkite,
the validation-only PR path runs without entering promotion or deployment, and
GitHub reports the `buildkite/network-change-delivery-platform` status context.
The validated PR path contains the pipeline upload, visible quality checks, and
pipeline-contract validation.

GitHub `main` protection is active. Three protected-main attempts established the
external acceptance history.

The first attempt passed shared validation and entered promotion, then failed
before promotion completed: host-side `uv run` created a native macOS ARM
environment and could not build `ansible-pylibssh==1.4.0` because
`libssh/libssh.h` was unavailable. It performed no deployment or device write
and did not reach deployment approval.

The correction moves Batfish readiness and NCDP assurance, promotion, and
verification into the pinned project container, connected to Batfish through an
explicit Compose service network. The host retains Git verification, Docker
orchestration, and artifact upload only.

The second attempt passed shared validation and created the containerized
promotion runner. It then failed before readiness because the arbitrary non-root
promotion UID could not read the root-owned readiness path copied from the
restrictive Buildkite checkout. Repeated permission failures ended in a
readiness timeout. No assurance result or completed promotion bundle was
produced; human approval and the deployment gate were not reached, and device
writes remained zero.

The image permission correction normalizes the immutable promotion runtime
tree for read/traverse/execute access by an arbitrary non-root UID while keeping
it non-writable and preserving restrictive host-owned promotion artifacts.

The third attempt, protected-main Buildkite build #11, completed the entire 7A
path for merged commit `8bb377958cd01c387503b1b11c80a13c4d6ae806`:
shared visible quality checks, pipeline-contract validation, serialized
main-only promotion, Batfish readiness, PASSED exact plan-bound assurance,
immutable promotion creation and verification, explicit human approval, and the
serialized deployment gate on `ncdp-deploy`. The approver entered exactly:

- Plan digest: `sha256:02a3bece7cc1f67ae77e4f3cd436d1366489fa63fddf7b3b442f7115866086f4`
- Assurance record digest: `sha256:2a0c364bdc1242fb5a884cf363a70066055bfb95ca75b71683493b428a0f9efa`
- Promotion digest: `sha256:1aa67a996e09ae8a7ab4024a4060991bbfa84ed5c4d0867e81e6cca26a869e4e`

The deployment gate downloaded the exact promotion artifact set from the
promotion step, independently verified the same commit and three digests, and
reported `deployment authorization gate: PASSED` and
`device write executed: NO`. The accepted run accessed no devices, CML, NetBox,
OpenBao, or secrets and performed no live deployment.

Build #11 establishes Increment 7A external acceptance. It does not complete
Increment 7 as a whole; workload identity was subsequently accepted in 7B, and
live deployment remains 7C.
