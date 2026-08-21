# Coding agent instructions

## Purpose and map

This repository is a greenfield reference platform for safe network-change
delivery. Application code lives in `src/network_change_delivery`, tests in
`tests`, product and architecture contracts in `docs`, CI configuration in
`.buildkite`, and repository policy in `.github`.

Read in this order: `README.md`, `docs/product/product-contract.md`,
`docs/architecture/overview.md`, `docs/architecture/security-boundaries.md`,
`docs/architecture/change-lifecycle.md`, `docs/threat-model.md`, applicable
ADRs, then `docs/roadmap.md`.

## Boundaries and discipline

Python owns policy, planning, rollout, evidence, and recovery decisions.
Execution providers own vendor operations; they are not policy engines. Preserve
honest vendor-specific safety semantics. Fail closed on unsupported, stale, or
ambiguous states. Resolve and preflight the complete fleet before writes; bind
approval and execution to one immutable plan; never imply fleet-wide atomicity.

Investigate before modifying. Make the smallest coherent change, preserve
unrelated work, do not weaken safety policy, and do not introduce features
outside requested scope. Add concrete files only. Update authoritative docs and
ADRs when contracts or decisions change; avoid duplicating normative prose.

Never include company data, credentials, or secrets. Never expose secrets in
logs or evidence. Do not commit, push, merge, rebase, force-push, delete branches,
rewrite history, or perform live network changes unless the task explicitly
authorizes that action.

## Testing and Git safety

Run `uv lock --check`, frozen dependency sync, Ruff lint and format checks,
pytest, package build, CLI smoke tests, Docker quality/runtime builds and runtime
smoke test, and `git diff --check` for baseline changes. Fix causes rather than
weakening gates. Inspect the complete diff and status before any authorized
commit. Do not alter unrelated branches or commits.

## Final report

Report the summary, files changed, decisions, every gate and Docker result,
image pins, limitations, exact commit and branch state, and PR URL when relevant.
State explicitly whether devices, company data, secrets, or remote deployment
systems were accessed or changed.
