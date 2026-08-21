# Network Change Delivery Platform

A greenfield, self-hosted reference platform for reviewed, validated, auditable,
recoverable, and observable network-change delivery across Cisco IOS/IOS XE and
Junos fleets.

**Current status:** Architecture Baseline 1. This repository currently contains
the product and architecture contracts, a Python CLI shell, a Docker foundation,
and a Buildkite quality-pipeline definition. No device automation or device
integration exists yet.

The first eventual vertical is a vendor-neutral managed interface-description
change with vendor-aware execution for Cisco IOS/IOS XE and Junos. GitHub owns
reviewed change inputs, Buildkite orchestrates future gates, Python owns policy
and lifecycle decisions, and execution adapters will own vendor operations.
NetBox, OpenBao, Batfish, CML, validation, history, and observability components
are selected future integrations, not current implementations.

Company data—including devices, credentials, configurations, addresses,
topology, and internal documentation—must never enter this repository.

## Local quality

```bash
uv sync --frozen --all-groups
uv run ruff check .
uv run ruff format --check .
uv run pytest
uv build
docker build --target quality --tag ncdp-quality:local .
docker build --target runtime --tag ncdp:local .
docker run --rm ncdp:local --version
```

Start with the [product contract](docs/product/product-contract.md), then read
the [architecture overview](docs/architecture/overview.md),
[security boundaries](docs/architecture/security-boundaries.md),
[change lifecycle](docs/architecture/change-lifecycle.md),
[threat model](docs/threat-model.md), [ADRs](docs/adr/), and
[roadmap](docs/roadmap.md).
