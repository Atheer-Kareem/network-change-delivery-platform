# Buildkite workflow

The current Buildkite pipeline is validation and assurance only. Profiled
exact-four disposable CML staging follows PR Batfish. It contains no device-write,
promotion, approval, or deployment-gate step. Real Buildkite staging acceptance
is pending the activation PR run.

```text
quality environment ----> lint / format / pytest / ansible-lint / build
committed diff ----------\
SNMP reproducibility -----+--> validation-complete --> profiled PR Batfish --> CML
observability runtime ----+
synthetic SNMPv3 ---------+
pipeline definition ------+
pipeline contract --------/
```

## Visible validation and barrier

`quality-env` builds the frozen validation image. Ruff lint, Ruff format,
pytest, ansible-lint, package build, and the containerized pipeline-contract
checks consume it. Committed-diff integrity, SNMP module reproducibility, and
Buildkite definition validation are independent roots. Observability and
synthetic SNMPv3 runtime validations are active, non-retriable hard gates.

All applicable checks converge at `validation-complete`. The separate
`buildkite-definition` step performs local parser/secret scanning, while
`ncdp-pipeline-contract` tests graph, queues, retry prohibition, change routing,
and the absence of deployment authority. Local agent worker capacity is an
operational detail, not a portable architecture contract.

## Profiled PR assurance

Runtime-relevant pull requests run `pr-batfish-assurance` after the barrier. It
normalizes and checks the exact profiled four-device candidate and current
service stack (`routed_underlay`, `ospf`, `vlan`, `acl`). Supplemental host
fixtures prove critical flows without becoming managed devices. The step has no
NetBox, OpenBao, CML, trust-store, or LIVE-device authority and cannot execute a
configuration command.

The wrapper verifies exact commit and PR context, runs on `ncdp-validation`, is
non-retriable, uses one serialized assurance concurrency group, publishes
typed secret-free evidence, and independently verifies it before success.

## Profiled CML integration gate

Exactly one top-level `cml-staging` job runs the reviewed
`.buildkite/scripts/profiled_cml_staging.sh` wrapper on `ncdp-staging`, serialized
at concurrency one in `ncdp/cml-ephemeral-staging`. Automatic and manual retries
are disabled; failures require a new commit/build and review of retained state.
It depends on both `validation-complete` and `pr-batfish-assurance` and has no
soft-fail or dependency-failure override. On main, the PR-only Batfish dependency
is skipped and satisfied, preserving the historical ADR 0027 independent CML
assurance branch after validation. Protected-main Batfish and delivery remain
retired.

The merge-control chain is runtime PR → validation → PR Batfish → CML →
aggregate Buildkite result → existing required GitHub status
`buildkite/network-change-delivery-platform` → merge allowed/blocked. A staging
failure makes that status unsuccessful. GitHub required-status configuration
remains an external operator-owned control, verified read-only through the main
ruleset during activation work; repository code does not modify it.

Staging reuses the accepted exact-four lifecycle and schema-v2 evidence. Its
agent-owned command hook admits canonical origin before sourcing protected
credentials; PR-controlled pipeline YAML alone cannot release them. See the
[operations runbook](buildkite-ephemeral-cml-staging-operations.md).

## Retired paths

The schema-v1 protected delivery group and exact-two disposable Terraform/CML
staging were historically implemented and accepted, then retired at the final
Detour-B deletion gate. Their commented pipeline blocks and privileged shell
entry points are removed. The obsolete exact-two Terraform/operator twin is no
longer validated or represented as current infrastructure.

Historical ADRs, acceptance reports, promotion models, and audit evidence keep
their original meaning. They do not grant current runtime authority. A future
protected-delivery capability must be designed against the profiled architecture
and reviewed as a new boundary; restoration of the old block is not an accepted
path. The replacement exact-four staging gate is separate from those retired
executors and retains the accepted transit-ios-01-only CML recycle.

## Runtime change classification

The identical PR Batfish and CML condition remains fail closed: all paths are
runtime-relevant except the reviewed documentation, repository-policy, and test-only
exclusions. A new top-level path defaults to runtime-relevant until its
classification is reviewed and covered by pipeline-contract tests.
