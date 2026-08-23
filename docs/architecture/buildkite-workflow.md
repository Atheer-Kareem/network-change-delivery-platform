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
verified commit and three exact approval digest values for the approver.

The promotion stage normalizes its immutable virtual environment, application
source, Batfish fixtures, and readiness path to read/traverse/execute permissions
without granting broad write access. Its root-owned image content is therefore
usable by the arbitrary host UID/GID selected for bind-mounted artifact
ownership, independent of checkout umask.

Promotion contains plan, policy, assurance, and frozen baseline bytes only.
The approval block stores its three digest fields as Buildkite build meta-data.
The gate retrieves those exact values with `buildkite-agent meta-data get`,
verifies exact digests, and prints an authorization summary, then stops.
There is no device, NetBox, or OpenBao access. OIDC identity and short-lived
OpenBao access are deferred to 7B (target lifetime 300 seconds).

The 7B-A application foundation adds a future deployment command that reads one
bounded Buildkite OIDC JWT from stdin and submits it to OpenBao's fixed JWT role.
OpenBao will validate the signed token and return mapped pipeline, commit,
branch, step, and job metadata; NCDP then compares that verified metadata with
the current deployment context. This command is not wired into the active
pipeline yet and performs no secret retrieval or deployment.

The personal lab may use one Mac, but queues, agent processes, working
directories, and deployment environment variables remain separate. Physical
host isolation is not claimed.
