# Buildkite workflow

The accepted pipeline architecture separates validation, disposable
integration, offline network assurance, immutable promotion, human
authorization, and protected deployment. During Detour B, automatic disposable
CML and the protected-delivery group are temporarily paused together while the
four-device Terraform realization is incomplete. Quality validation, Terraform
static validation, PR Batfish candidate assurance, and the restored
observability-runtime and synthetic-SNMPv3 runtime checks remain active. The
two restored runtime checks are temporarily `soft_fail` while their
Buildkite-runtime behavior is reconciled after Detour B; they remain visible,
change-aware validation rather than accepted hard gates.

```text
runtime pull request                 non-PR main during B3 pause

visible validation                  visible validation
        |                                    |
validation-complete                 validation-complete
        |                                    |
PR Batfish · profiled four-device           done
        |
       done
```

The preserved `cml-staging` and complete `protected-delivery` YAML blocks are
commented out, not bypassed. Promotion has not had its CML dependency removed,
and no live-delivery path remains active without staging. Restore the two blocks
together only when the operator explicitly decides disposable CML staging is
useful again and its Terraform topology is ready for the intended profiled
population.

## Visible validation and barrier

There is no visible `quality` group. `quality-env` builds the frozen
`quality-base` environment used only by validations that consume it: Ruff lint,
Ruff format, ordinary pytest, ansible-lint, package build, and the containerized
half of the NCDP pipeline contract. Those checks can run independently after
the image exists.

Committed-diff integrity, Terraform CML static validation, SNMP module
reproducibility, and Buildkite-definition validation are independent roots.
Observability-runtime and synthetic-SNMPv3 validation are active siblings that
depend on `quality-env`, run on `ncdp-validation`, have automatic retry
disabled, and retain bounded `if_changed` routing. Both temporarily use plain
`soft_fail: true`. The synthetic-SNMP Buildkite command disables its otherwise
default nested observability regression with
`NCDP_SKIP_OBSERVABILITY_REGRESSION=1`, so the dedicated observability step is
the sole first-class management-service runtime validator. This follows the
observed duplicate Docker identity collision; it does not diagnose the remaining
Buildkite-only failures or treat successful local runtime validation as proof.

Two visible contracts have distinct meanings:

- `buildkite-definition` uses the installed agent to dry-run the pipeline with
  secret and parse-warning rejection;
- `ncdp-pipeline-contract` combines containerized structural assertions with
  genuine host-installed-agent changed-file routing evaluation. It covers the
  graph, queues, gating, retry prohibition, and runtime-path classification.

All applicable validations join at the keyed `validation-complete` wait.
Legitimately skipped change-aware steps satisfy the barrier. The active PR
Batfish step explicitly depends on it. The preserved staging definition still
records its dependency on both the barrier and PR Batfish for any explicitly
authorized restoration, but it is not parsed as an active step during the
pause.
Validation runs on the `ncdp-validation` queue. Local worker capacity is an
operational setting and is not a portable platform contract.

## Pull requests and disposable staging

Runtime-relevant pull requests run `pr-batfish-assurance` after validation. It
performs offline normalized behavioral assurance against the exact profiled
four-device managed-network candidate and current explicit service stack.
B4-4's stack is `routed_underlay, ospf, vlan, acl`; its inputs are the accepted B3-5,
B4-2 routing-identity, and B4-3 VLAN/gateway evidence copies plus the Git-owned
profile catalog. Two supplemental Batfish-only host fixtures make six modeled
nodes without changing the four managed devices. The current path performs
differential B4-3-baseline/B4-4-secured behavior assurance for the exact
Git-owned ACL. It does
not call NetBox, OpenBao, CML, LIVE devices, or trust material. During the
Detour B pause it is the last active
network-assurance step; no disposable CML job follows it.

When restored, CML staging is independently serialized in
`ncdp/cml-ephemeral-staging`, cannot be retried, and uses build-UUID run
identity, external run-scoped state, dedicated identities, strict run-scoped
host trust, and sanitized evidence. A trusted agent command hook rejects fork
PR staging before credentials are exposed.

The preserved staging job remains one Python lifecycle owner. When restored,
its visible create → validate → destroy phases do not split cleanup authority
across Buildkite jobs. It verifies the real IOS XE/Junos disposable runtime and
read-only provider paths; it does not apply or validate the proposed live
candidate. Batfish and CML therefore provide complementary model and
vendor-runtime evidence.
See [Buildkite ephemeral CML staging operations](buildkite-ephemeral-cml-staging-operations.md).

The protected-delivery group remains restricted by its preserved definition to
non-PR `main` builds, but the entire group is currently commented out and is
therefore unavailable on every build.

A fork-origin runtime PR may run unprivileged validation and Batfish but cannot
receive trusted staging credentials. If the operator restores the staging gate,
a maintainer must reproduce or adopt that commit in the canonical repository
before the CML merge gate can pass.

## Protected-main assurance and promotion

This entire accepted branch is temporarily inactive and remains legacy v1. If
the operator explicitly restores it with CML staging before its later migration,
a runtime-relevant non-PR `main` build will again make the legacy
`batfish-assurance` and `cml-staging` eligible independently after
`validation-complete`.
Batfish uses the `ncdp-validation` queue, concurrency group
`ncdp/batfish-assurance`, limit one, and no automatic or manual retry. Its fixed
Compose project is `ncdp-batfish-assurance`. The step verifies commit identity,
starts Batfish, performs bounded readiness, evaluates the exact plan/policy/
baseline, independently verifies successful evidence, uploads
`assurance/assurance.json`, and publishes a typed sanitized annotation.

`promotion` depends explicitly on both `cml-staging` and
`batfish-assurance`. It does not start, contact, or wait for Batfish. It
downloads exactly `assurance/assurance.json` from step `batfish-assurance` in
the current Buildkite build, requires the exact filesystem shape, rejects
symlinks/non-regular material, and independently verifies the record against
the checked-out plan, policy, and baseline. Only then does it create and verify
the immutable promotion, upload `promotion/**`, and record the plan, assurance,
and promotion digests as `promoted-*` metadata.

The profiled PR artifact is never promotion input. The preserved legacy
promotion remains hard-scoped to the same-build step key `batfish-assurance`,
not `pr-batfish-assurance`. Migrating protected assurance/promotion is a later
decision after the profiled service and accepted-state execution architecture
is ready.

Promotion contains plan, policy, assurance, and frozen baseline bytes only.
Buildkite pauses at the fieldless `deployment-approval` block after promotion.
Its successful completion is explicit human authorization of that exact
promotion; automated metadata remains evidence rather than authorization.

## Protected deployment

Protected delivery remains paused while CML staging is disabled. Restore both
together only by explicit operator decision. After restoration, the serialized
`deploy-gate` runs on `ncdp-deploy` in
`ncdp/network-change-deployment`, limit one, with automatic and manual retries
disabled. It independently verifies the promotion artifact and its three
recorded digests. A changed commit-bound live request must bind exactly to that
promotion before a device-capable identity is requested. An unchanged or absent
request terminates in the accepted no-write path before privileged device
authority.

Buildkite OIDC and OpenBao bind pipeline, commit, branch, step, and job identity.
Device-specific, short-lived, one-use authority is derived only after request,
promotion, runtime, audit, and fresh preflight checks. For a write, the same
non-retryable job captures Oxidized PRE, performs one vendor-aware attempt,
attempts POST, and publishes typed AuditStore correlation. Ambiguous or failed
writes are never replayed inside the historical build. See
[Buildkite protected live deployment](buildkite-live-deployment.md).

The personal lab may use one Mac, but validation, staging, and deployment
queues, agent processes, working directories, hooks, and environment authority
remain separate. Physical host isolation is not claimed.

## Live-path change classification

The repository pipeline's native Buildkite `if_changed` exclusion set is the
executable classification authority. Visible validation and contract checks run
for every build. Active PR Batfish is omitted only when every changed path is
one of `docs/**`, `README.md`,
`AGENTS.md`, `.github/CODEOWNERS`, `.github/pull_request_template.md`,
`tests/**`, or `.gitignore`. The condition includes `**` first, so mixed changes
and unknown or unclassified paths retain the runtime path. Indeterminate
classification fails closed by running guarded steps.

New top-level paths are runtime-relevant by default. An exclusion requires
explicit rationale, updated architecture, pipeline-contract regression
coverage, and review. Documentation and tests describe and protect this policy;
they do not implement a second classifier.

GitHub must require the aggregate
`buildkite/network-change-delivery-platform` status on `main`. With that
external rule, a runtime PR Batfish failure fails the aggregate status and
prevents merge during this pause. See
[ADR 0027](../adr/0027-pre-merge-network-assurance.md).
