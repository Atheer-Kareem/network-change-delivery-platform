# Network Change Delivery Platform

A self-hosted reference NetDevOps platform for reviewed, validated, auditable,
recoverable, and observable multi-vendor network changes across Cisco IOS/IOS XE
and Junos.

## What it demonstrates

- Git-reviewed network changes
- Cisco and Junos multi-vendor delivery
- Pre-change validation and assurance
- Controlled fleet rollout
- Independent post-change verification
- Audit, recovery, and continuous observability

## Current status

- The reference platform implements reviewed Cisco IOS XE and Junos planning,
  controlled delivery, protected Buildkite promotion/deployment, ephemeral CML
  staging, append-only audit/configuration observation, and persistent
  reachability dashboards and alerts.
- The personal-lab model has two managed routers with NetBox inventory,
  OpenBao credential authority, a manually owned live CML realization, and a
  separate Terraform-owned ephemeral staging realization.
- No production or company infrastructure or data is used.

## Architecture

The platform separates reviewed intent, workflow orchestration, policy, vendor
execution, validation, evidence, and operations. See the
[architecture overview](docs/architecture/overview.md).

## Documentation

- [Product contract](docs/product/product-contract.md)
- [Architecture](docs/architecture/overview.md)
- [Security boundaries](docs/architecture/security-boundaries.md)
- [Change lifecycle](docs/architecture/change-lifecycle.md)
- [Architecture decision records](docs/adr/)
- [Roadmap](docs/roadmap.md)
