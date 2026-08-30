# ADR 0027: Pre-merge network assurance

## Status

Proposed

## Context

The accepted protected-main path independently runs Batfish plan assurance and
disposable CML staging before immutable promotion. Before this decision,
runtime-relevant pull requests ran CML staging but did not run Batfish. An
invalid modeled network behavior could therefore be discovered only after the
change had merged to `main`, even though the reviewed pull-request commit
already contained the exact plan, policy, and frozen baseline required for
offline assurance.

Batfish and CML prove complementary properties. Batfish derives a candidate
from the exact reviewed plan and frozen baseline, then evaluates normalized
critical flows, invariants, and differential reachability without live routers.
CML creates the disposable vendor topology, verifies topology and stored Day-0,
starts IOS XE and Junos, proves readiness and strict host trust, and exercises
the real read-only NCDP planning/provider paths before exact destroy and
independent absence verification. CML does not apply or validate the proposed
live candidate configuration.

## Decision

Every runtime-relevant pull request runs the top-level
`pr-batfish-assurance` step after `validation-complete`. Successful PR Batfish
assurance is an explicit prerequisite for `cml-staging`, so the cheaper offline
model check fails before the approximately five-minute disposable CML lifecycle
can create resources. Both steps remain serialized, non-retriable boundaries;
failure requires a corrected commit and a new build.

The PR Batfish step reuses the same assurance script, fixed Compose project,
plan, policy, frozen baseline, candidate derivation, verification, typed
evidence, and sanitized annotation as protected main. It receives no device,
CML, NetBox, OpenBao, AuditStore, Oxidized, or deployment authority.

The runtime-path classifier remains deliberately broad and fail closed:
`include: "**"` with only the existing reviewed documentation, test, and
presentation exclusions. PR Batfish and CML use the identical condition. A
new or unknown runtime path therefore runs both rather than depending on a
narrow network-file allowlist that could omit a future sensitive path.

Protected `main` remains an independent trust boundary. Its
`batfish-assurance` and `cml-staging` branches still fan out after
`validation-complete`, and immutable promotion still joins those exact
same-main-build results. Promotion downloads assurance only from the
`batfish-assurance` step in that merged-main build. It never consumes the PR
artifact.

Candidate derivation remains inside the typed assurance operation. NCDP already
binds the exact plan, policy, frozen baseline, derived candidate, snapshot
digests, flow results, invariants, and self-digested record. A separate
“Generate Candidate” artifact step would create another handoff without adding
a present safety property, so this decision deliberately does not add one.

The aggregate GitHub status
`buildkite/network-change-delivery-platform` must be a required check for
`main`. The intended merge-control chain is runtime PR → Batfish/CML failure →
aggregate Buildkite failure → required status unsatisfied → merge blocked.
Pipeline structure alone cannot enforce that repository setting.

The trusted staging-agent hook continues rejecting fork-origin PRs before
loading credentials. A runtime-affecting fork PR cannot directly satisfy the
trusted CML merge gate; a maintainer must reproduce or adopt the commit in the
canonical repository and obtain a fresh canonical Buildkite run.

## Consequences

Runtime pull requests gain model-based candidate assurance before expensive
real-vendor read-only integration validation. Documentation/test-only changes
continue to skip both guarded stages, while mixed and unknown changes run them.

PR assurance is prevention evidence, not promotion authority. The merge commit
may differ from its PR head and protected main has stronger authorization
semantics, so main pays the deliberate cost of independently regenerating both
Batfish and CML evidence. No protected deployment, live intent, device-write,
credential, staging-authority, or retry contract changes.

GitHub required-status configuration remains an external operator-owned
control. Until the implementation PR and its merged-main build prove the DAG,
this ADR remains proposed and Increment 12F/12G remain paused.
