# ADR 0007: Batfish assurance boundary

## Status

Accepted for Increment 6A.

## Decision

Batfish is an offline assurance service, not an execution provider. Python owns
assurance policy and pass/fail decisions; Pybatfish/Batfish owns network-model
computation behind an explicit normalized provider boundary. Batfish receives
only explicit synthetic snapshot inputs and never discovers production devices.

Platform-owned SHA-256 snapshot manifests bind every input file without storing
raw configurations. Raw configurations, traces, parser dumps, DataFrames, and
arbitrary server responses are not evidence. Parser and initialization findings
remain first-class bounded evidence because Batfish cannot model every vendor
feature perfectly.

Increment 6A uses a generic `subject_digest`. Binding assurance to an exact
`DeploymentPlan` or `FleetDeploymentPlan` is deferred to Increment 6B.
Assurance is not yet a `fleet-deploy` prerequisite; Buildkite enforcement
belongs to Increment 7.

## Consequences

The first vertical covers deterministic mixed-vendor snapshots, exact node
sets, zero initialization issues, critical-flow reachability, and differential
reachability. Provider failures fail closed as bounded `BLOCKED` evidence.
