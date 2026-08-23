# Buildkite external acceptance

This document records the external Buildkite and GitHub acceptance for Increment 7.

PR-side external acceptance is verified. GitHub pull requests trigger Buildkite,
the validation-only PR path runs without entering promotion or deployment, and
GitHub reports the `buildkite/network-change-delivery-platform` status context.
The validated PR path contains the pipeline upload, visible quality checks, and
pipeline-contract validation.

GitHub `main` protection is now active. Main-branch Buildkite execution acceptance
remains pending. The first protected-main attempt passed shared validation and
entered promotion, then failed before promotion completed: host-side `uv run`
created a native macOS ARM environment and could not build
`ansible-pylibssh==1.4.0` because `libssh/libssh.h` was unavailable. It performed
no deployment or device write and did not reach deployment approval.

The correction moves Batfish readiness and NCDP assurance, promotion, and
verification into the pinned project container, connected to Batfish through an
explicit Compose service network. The host retains Git verification, Docker
orchestration, and artifact upload only.

The second protected-main attempt passed shared validation and created the
containerized promotion runner. It then failed before readiness because the
arbitrary non-root promotion UID could not read the root-owned readiness path
copied from the restrictive Buildkite checkout. Repeated permission failures
ended in a readiness timeout. No assurance result or completed promotion bundle
was produced; human approval and the deployment gate were not reached, and
device writes remained zero.

The image permission correction now normalizes the immutable promotion runtime
tree for read/traverse/execute access by an arbitrary non-root UID while keeping
it non-writable and preserving restrictive host-owned promotion artifacts. This
does not yet establish successful main-path 7A acceptance: a later protected-main
run must complete promotion, reach human approval, and pass the no-write
deployment gate.
