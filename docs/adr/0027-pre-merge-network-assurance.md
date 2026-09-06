# ADR 0027: Pre-merge network assurance

## Status

Proposed

## Context

The historically accepted protected-main path independently ran Batfish plan
assurance and disposable CML staging before immutable promotion. Before this
decision,
runtime-relevant pull requests ran CML staging but did not run Batfish. An
invalid modeled network behavior could therefore be discovered only after the
change had merged to `main`, even though the reviewed pull-request commit
already contained the exact plan, policy, and frozen baseline required for
offline assurance.

Batfish and CML prove complementary properties. Batfish derives a candidate
from the exact reviewed plan and frozen baseline, then evaluates normalized
critical flows, invariants, and differential reachability without live routers.
CML creates the disposable vendor topology, verifies topology and stored Day-0,
starts the exact-four profiled population, proves readiness and strict host trust,
and exercises real read-only NCDP provider paths before exact destroy and
independent absence verification. CML does not apply or validate the proposed
live candidate configuration.

## Decision

Every runtime-relevant pull request runs the top-level
`pr-batfish-assurance` step after `validation-complete`. Successful PR Batfish
assurance is an explicit prerequisite for `cml-staging`, so the cheaper offline
model check fails before the disposable CML lifecycle
can create resources. Both steps remain serialized, non-retriable boundaries;
failure requires a corrected commit and a new build.

The original PR Batfish step reused the same assurance script, fixed Compose
project, plan, policy, frozen baseline, candidate derivation, verification,
typed evidence, and sanitized annotation as protected main. It received no
device, CML, NetBox, OpenBao, AuditStore, Oxidized, or deployment authority.

B4-1A refines this proposed decision after the four-device profile architecture
became current truth. The single active PR step uses a separate offline
profiled four-device entry point and evidence model. At that point the legacy
shared script admitted only the disabled protected `batfish-assurance` context. This
did not itself migrate or retire protected delivery. The later Detour-B deletion
gate retired protected delivery and exact-two staging. The current activation
reuses PR #134's locally accepted exact-four lifecycle, including its narrowly
fenced transit-ios-01-only CML STOP/START recycle, with the existing staging JWT
identity for devices 1/2/8/9. It adds no device CLI write or B4 D1 activation.

The runtime-path classifier remains deliberately broad and fail closed:
`include: "**"` with only the existing reviewed documentation, test, and
presentation exclusions. PR Batfish and CML use the identical condition. A
new or unknown runtime path therefore runs both rather than depending on a
narrow network-file allowlist that could omit a future sensitive path.

Main retains independent real-platform assurance after `validation-complete`.
The PR-only Batfish dependency is skipped and satisfied on main, using the same
DAG as the historically accepted `ab55c30` pipeline. The current pipeline has
no protected-main `batfish-assurance`, promotion, or protected-delivery branch.
Historical same-main-build promotion binding remains historical; any future
protected profiled delivery requires a separate design.

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
may differ from its PR head, so main independently reruns CML assurance after
validation. Staging injects the existing one-use, device-scoped OpenBao provider
into the shared exact-four lifecycle. It preserves the trusted-agent hook,
no-retry contract, and protected delivery retirement. It does not broaden local
profiled-deploy authority or modify NCDP Live.

GitHub required-status configuration remains an external operator-owned
control. Read-only activation inspection verified that the main ruleset requires
the existing aggregate Buildkite status with strict status checks. Real
Buildkite staging acceptance remains PENDING. Until the activation PR and its
merged-main build prove the DAG, this ADR remains proposed and Increment
12F/12G remain paused.
