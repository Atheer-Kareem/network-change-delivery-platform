# Buildkite workflow

The current pipeline makes validation, disposable integration, offline network
assurance, immutable promotion, human authorization, and protected deployment
separate visible boundaries.

```text
runtime pull request                 protected non-PR main

visible validation                  visible validation
        |                                    |
validation-complete                 validation-complete
        |                               |             |
PR Batfish candidate assurance      CML staging      Batfish assurance
        |                               |             |
CML staging                            +------+------+
create -> READ-ONLY validate                  |
       -> destroy                     immutable promotion
                                               |
                                      human authorization
                                               |
                                          deploy-gate
```

## Visible validation and barrier

There is no visible `quality` group. `quality-env` builds the frozen
`quality-base` environment used only by validations that consume it: Ruff lint,
Ruff format, ordinary pytest, ansible-lint, package build, applicable
observability/SNMP runtime validation, and the containerized half of the NCDP
pipeline contract. Those checks can run independently after the image exists.

Committed-diff integrity, Terraform CML static validation, SNMP module
reproducibility, and Buildkite-definition validation are independent roots.
Change-aware observability and SNMP validations may be skipped when their
reviewed paths do not change.

Two visible contracts have distinct meanings:

- `buildkite-definition` uses the installed agent to dry-run the pipeline with
  secret and parse-warning rejection;
- `ncdp-pipeline-contract` combines containerized structural assertions with
  genuine host-installed-agent changed-file routing evaluation. It covers the
  graph, queues, gating, retry prohibition, and runtime-path classification.

All applicable validations join at the keyed `validation-complete` wait.
Legitimately skipped change-aware steps satisfy the barrier. The PR Batfish
step and protected-delivery group explicitly depend on it. `cml-staging`
explicitly depends on both the barrier and the PR Batfish step; Buildkite treats
the PR-only dependency as satisfied when that step is conditionally skipped on
main.
Validation runs on the `ncdp-validation` queue. Local worker capacity is an
operational setting and is not a portable platform contract.

## Pull requests and disposable staging

Runtime-relevant pull requests first run `pr-batfish-assurance` after
validation. It performs offline normalized behavioral assurance against the
exact reviewed plan, policy, frozen baseline, and derived candidate. Only after
it passes can the single `cml-staging` job run. Batfish and staging share the
same broad fail-closed runtime change classification, and both require a fresh
commit/build after failure rather than a retry.

CML staging is independently serialized in
`ncdp/cml-ephemeral-staging`, cannot be retried, and uses build-UUID run
identity, external run-scoped state, dedicated identities, strict run-scoped
host trust, and sanitized evidence. A trusted agent command hook rejects fork
PR staging before credentials are exposed.

The staging job remains one Python lifecycle owner. Its visible create →
validate → destroy phases do not split cleanup authority across Buildkite jobs.
It verifies the real IOS XE/Junos disposable runtime and read-only provider
paths; it does not apply or validate the proposed live candidate. Batfish and
CML therefore provide complementary model and vendor-runtime evidence.
See [Buildkite ephemeral CML staging operations](buildkite-ephemeral-cml-staging-operations.md).

The protected-delivery group is restricted to non-PR `main` builds and is
therefore absent/ineligible on pull requests.

A fork-origin runtime PR may run unprivileged validation and Batfish but cannot
receive trusted staging credentials. A maintainer must reproduce or adopt that
commit in the canonical repository before the CML merge gate can pass.

## Protected-main assurance and promotion

On a runtime-relevant non-PR `main` build, `batfish-assurance` and
`cml-staging` become eligible independently after `validation-complete`.
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

The PR artifact is never promotion input. Protected main independently
re-establishes assurance for the exact merged commit, and promotion remains
hard-scoped to the same-build step key `batfish-assurance`, not
`pr-batfish-assurance`.

Promotion contains plan, policy, assurance, and frozen baseline bytes only.
Buildkite pauses at the fieldless `deployment-approval` block after promotion.
Its successful completion is explicit human authorization of that exact
promotion; automated metadata remains evidence rather than authorization.

## Protected deployment

The serialized `deploy-gate` runs on `ncdp-deploy` in
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
for every build. PR Batfish, CML staging, and the protected-delivery group are
omitted only when every changed path is one of `docs/**`, `README.md`,
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
external rule, a runtime PR Batfish or CML failure fails the aggregate status
and prevents merge. See [ADR 0027](../adr/0027-pre-merge-network-assurance.md).
