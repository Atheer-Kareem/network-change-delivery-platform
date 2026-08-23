# Buildkite workflow

The 7A DAG is `quality` → `pipeline-contract` → `promotion` →
`deployment-approval` → serialized `deploy-gate`. `quality` is a visible group:
one step builds a frozen `quality-base` Docker environment, then separate steps
run the committed-diff, Ruff, pytest, ansible-lint, and package checks. The five
tool checks reuse that exact build image. Validation uses `ncdp-validation`; the
gate uses `ncdp-deploy` with concurrency group
`ncdp/network-change-deployment` and limit one.

Pull requests run only the shared validation steps. Promotion and approval are
main, non-PR steps. Promotion has its own concurrency limit one and group
`ncdp/batfish-promotion`. The host verifies Git identity and orchestrates Docker
and artifact upload; readiness, assurance, bundle creation, and verification run
in the pinned project promotion image. Docker Compose attaches that container
and Batfish to the deterministic `ncdp-promotion` project network, where both
readiness and assurance use `NCDP_BATFISH_HOST=batfish`. Promotion writes through
a bounded bind mount before the host agent uploads the artifact. Deployment
serialization protects write execution separately. Promotion prints the
verified commit and three exact promotion digest values for visibility.

The promotion stage normalizes its immutable virtual environment, application
source, Batfish fixtures, and readiness path to read/traverse/execute permissions
without granting broad write access. Its root-owned image content is therefore
usable by the arbitrary host UID/GID selected for bind-mounted artifact
ownership, independent of checkout umask.

Promotion contains plan, policy, assurance, and frozen baseline bytes only.
After repository-owned verification, manifest confirmation, and successful
artifact upload, promotion independently re-verifies the bundle and records the
plan, assurance, and promotion digests as `promoted-*` Buildkite build metadata.
Buildkite then pauses at a fieldless `deployment-approval` block. Its successful
completion is the explicit human authorization of the exact promotion belonging
to that build; the human does not manually transcribe or independently compare
digests. The deployment gate downloads and independently verifies the artifact,
then requires its three verified digests to match the machine-recorded promoted
values exactly. The separation is promotion records → human authorizes → gate
verifies. Automated metadata is evidence, not authorization, and the gate still
depends on the human block.

The deployment gate reads one bounded Buildkite OIDC JWT from stdin and submits
it to OpenBao's fixed JWT role. The main, non-PR job requests that JWT with
audience `urn:ncdp:openbao:deploy`,
300-second lifetime, and `pipeline_id` as its subject claim. This makes the
immutable pipeline UUID both the JWT subject and an explicit mapped claim.
OpenBao validates the signed token and returns mapped pipeline, commit, branch,
step, and job metadata; NCDP then compares that verified metadata with the
current deployment context. The job rejects ambient AppRole bootstrap and
direct device credentials before requesting identity. Only after identity
verification does it retrieve and verify the promotion artifact and promoted
metadata. Final authorization success therefore requires both cryptographic
workload identity and exact promotion verification. The issued OpenBao token has
no policies and is discarded; the active gate performs no secret retrieval or
deployment. External OpenBao configuration and protected-main federation
acceptance remain pending.

The personal lab may use one Mac, but queues, agent processes, working
directories, and deployment environment variables remain separate. Physical
host isolation is not claimed.
