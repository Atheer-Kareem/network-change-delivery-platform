# Buildkite workflow

The 7A DAG is `quality` → `pipeline-contract` → `promotion` →
`deployment-approval` → serialized `deploy-gate`. Validation uses
`ncdp-validation`; the gate uses `ncdp-deploy` with concurrency group
`ncdp/network-change-deployment` and limit one.

Promotion contains plan, policy, assurance, and frozen baseline bytes only.
The gate verifies exact digests and prints an authorization summary, then stops.
There is no device, NetBox, or OpenBao access. OIDC identity and short-lived
OpenBao access are deferred to 7B (target lifetime 300 seconds).

The personal lab may use one Mac, but queues, agent processes, working
directories, and deployment environment variables remain separate. Physical
host isolation is not claimed.
