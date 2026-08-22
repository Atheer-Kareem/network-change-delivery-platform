# Buildkite external acceptance

This document records the external Buildkite and GitHub acceptance for Increment 7.

PR-side external acceptance is verified. GitHub pull requests trigger Buildkite,
the validation-only PR path runs without entering promotion or deployment, and
GitHub reports the `buildkite/network-change-delivery-platform` status context.
The validated PR path contains the pipeline upload, visible quality checks, and
pipeline-contract validation.

Main-branch acceptance remains pending. This does not yet establish main branch
protection or acceptance of the main-only promotion, approval, or deployment
gate path.
