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

Three rejected PR-build diagnostics remained entirely before Terraform creation.
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

Build #83 verified the corrected Buildkite, NetBox, OpenBao, and CML identity
boundaries, then failed before Terraform initialization because Terraform was
not installed on the dedicated agent path. Its sanitized evidence recorded run
ID `bk-01a03a31-933d-46b0-a55c-18454cb24191`, no lab/node/link realization,
no creation, no cleanup attempt, and no cleanup failure. The run directory held
only an empty Terraform data directory and no state. Terraform 1.15.8 was then
installed at the agent's Homebrew path and the dedicated agent was restarted.
Build #83 was not retried; acceptance proceeds through a distinct build-bound
run identity.

Build #84 crossed the live lifecycle boundary with run ID
`bk-01a03a42-ea65-4a45-b48e-1dce08ceb89d`. It created the exact 13-resource
topology under lab `00f3caf8-2d8b-41c9-b44e-d7168234a768`, reached management
readiness, and then failed closed during core-02 NCDP read-only validation. The
run-scoped known-hosts path had been passed through `ANSIBLE_SSH_COMMON_ARGS`,
but the pinned Ansible libssh connection accepts only `ProxyCommand` from that
option. The adapter now supplies the strict run-scoped trust configuration
through libssh's supported `ANSIBLE_LIBSSH_CONFIG_FILE` boundary.

Build #84 also exposed that Terraform initially created its credential-bearing
state with the agent's permissive process umask before the driver applied its
post-command `0600` correction. The exact live state file was immediately
restricted to `0600`; the Buildkite shell and shared Python entry point now
both set umask `077`, with regression coverage. Despite the primary validation
failure, direct destroy, independent CML absence, empty-state verification, and
state retirement all passed. Build #84 had no cleanup failure and was not
retried.

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
