# Increment 8E-3 Buildkite ephemeral CML staging acceptance

## Static boundary

Increment 8E-3 started from merged `main`
`637da951857a6fe68f8b4af14fb4ff1d320183e0`. It adds serialized staging after
quality and pipeline-contract and before main-only promotion, preserving human
approval and deploy-gate semantics. It invokes the accepted 8E-2 lifecycle and
keeps network-intent validation read-only.

External acceptance is pending. This increment is not accepted until a
same-repository PR build records the following evidence.

Static implementation and prerequisite setup passed before that build. The
`ncdp-staging` queue exists with concurrency controlled by the pipeline, and its
dedicated agent registered with an external mode-0700 state root and trusted
command hook. The two exact OpenBao staging policies/roles were configured and
read back. NetBox has one dedicated service user, one write-disabled v2 token,
and only the existing view permission for `dcim.device` and `dcim.interface`.
CML 2.10 personal licensing rejected creation of an additional regular user;
acceptance therefore uses the existing personal-controller operator login to
mint a process-memory bearer while rejecting ambient `CML2_TOKEN`. No CML lab,
node, or link was created during prerequisite setup.

Two rejected PR-build diagnostics remained entirely before Terraform creation.
Build #81 exposed reliance on a shell-hook path variable that Buildkite only
documents for polyglot hooks; no evidence or state directory was produced. The
agent-owned command hook now loads its protected credential file from the
documented `$HOME` configuration boundary after admission. Build #82 then
produced sanitized failure evidence for a dedicated NetBox v2 token stored as
only its plaintext component. The unusable token was revoked and replaced with
the complete NetBox v2 bearer presentation; status-only checks for status,
device, and interface endpoints returned HTTP 200. Build #82 had
`creation_outcome=not_attempted`, `destroy_outcome=not_attempted`, no run state,
and zero CML mutations. Neither failed job was retried.

## External PR build

- Buildkite build/ID: pending
- tested commit: pending
- `cml-staging` job ID and run ID: pending
- fresh lab/node/link IDs: pending
- core-02 and edge-junos readiness: pending
- NCDP read-only validation: pending
- direct destroy from STARTED: pending
- independent CML absence and state retirement: pending
- sanitized artifact/digest: pending
- final CML staging count: pending
- console operations/device writes: expected zero

The PR remains unmerged. A later merged-main build is a separate check that the
same staging gate precedes promotion for the merged commit.
