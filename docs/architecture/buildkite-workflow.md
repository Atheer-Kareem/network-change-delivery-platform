# Buildkite workflow

The 7A DAG is `quality` → `pipeline-contract` → `promotion` →
`deployment-approval` → serialized `deploy-gate`. Validation uses
`ncdp-validation`; the gate uses `ncdp-deploy` with concurrency group
`ncdp/network-change-deployment` and limit one.

Pull requests run only the shared validation steps. Promotion and approval are
main, non-PR steps. Promotion has its own concurrency limit one and group
`ncdp/batfish-promotion`, because the local service is fixed to loopback port
9996; deployment serialization protects write execution separately. Promotion
waits for an actual Batfish server-version request before assurance and prints
the verified commit and three exact approval digest values for the approver.

Promotion contains plan, policy, assurance, and frozen baseline bytes only.
The approval block stores its three digest fields as Buildkite build meta-data.
The gate retrieves those exact values with `buildkite-agent meta-data get`,
verifies exact digests, and prints an authorization summary, then stops.
There is no device, NetBox, or OpenBao access. OIDC identity and short-lived
OpenBao access are deferred to 7B (target lifetime 300 seconds).

The personal lab may use one Mac, but queues, agent processes, working
directories, and deployment environment variables remain separate. Physical
host isolation is not claimed.
