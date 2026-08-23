# Buildkite protected live deployment

7C-A adds a fail-closed, single-device composition boundary without changing the
existing vendor execution lifecycle. Every protected-main build still performs
the accepted zero-policy 7B identity exchange and exact promotion verification.
The gate then checks whether that exact commit changed the fixed live request
relative to its first parent. Authorization reads the bounded regular blob
directly from that commit's Git object; working-tree creation, modification,
deletion, symlinks, and oversized content cannot substitute request semantics.

An unchanged or deleted request prints `live deployment requested: NO` and
`device write executed: NO`, then exits before a privileged JWT, NetBox, OpenBao
credential read, or device access. A changed request must exist and bind exactly
to the promoted `DeploymentPlan` by change ID, digest, and
`netbox:dcim.device:<id>` identity. Extra fields, fleet plans, local inventory,
environment credential provenance, and arbitrary secret paths are rejected.

After request validation, the gate verifies the deployment agent has every
collection and exact version pinned by `ansible/requirements.yml`. It uses the
same effective collection search path as the Cisco adapter and performs only
deterministic filesystem and collection-metadata inspection. Collections are
provisioned separately into an agent-owned persistent path; the privileged job
does not install from Galaxy. Only after this check passes does the gate obtain
a second fresh Buildkite JWT using the accepted audience, lifetime, and
`pipeline_id` subject selection. It pipes the JWT directly to
`deploy-buildkite-promotion`. The command re-verifies the promotion and request,
creates `NetBoxInventoryProvider`, derives the device-specific OpenBao role and
credential path only from stable NetBox identity, and calls `deploy_plan()` with
the promoted plan digest as approval. This preserves fresh inventory/device
preflight, stale-plan checks, vendor-specific execution and recovery, and
independent post-write validation.

The device-specific OpenBao token has one use, no default policy, no Identity or
external-namespace capability, and exactly one read policy. That use is consumed
by `GET /v1/ncdp/data/devices/<id>/ssh`. The JWT, OpenBao token, NetBox token,
username, and password never enter arguments, logs, artifacts, metadata, plans,
or evidence. The mode-0600 typed `ChangeRecord` is uploaded after execution even
when the deployment outcome is nonzero. The gate then preserves that original
failure status; an upload failure also fails the job. A failure before evidence
exists fabricates no artifact and reports that no typed record was produced.

7C-A supports one promoted `DeploymentPlan`; Buildkite fleet deployment remains
unsupported. NetBox access is inventory-read-only and NCDP performs no NetBox
mutation. This foundation has no active live request and has not performed or
externally accepted a device write.

7C-B1 replaces the active synthetic fleet promotion input with the exact
repository-owned single-device plan under `deployments/live/promotion`. The plan
was generated through fresh read-only NetBox, OpenBao, and device boundaries.
Its dedicated baseline is a sanitized plan-bound Batfish model that preserves
the accepted synthetic critical flow and exact interface-description
precondition; it is not a claim of full live configuration freshness. B1 keeps
`deployments/live/request.yaml` absent so protected-main can first validate the
single-device promotion and terminate in the established no-write path. Live
device-write acceptance remains pending.

The first externally attempted 7C deployment stopped during preflight with a
`BLOCKED` outcome before execution. Pre-write failures remain fail-closed, while
the existing `StageResult.message` now attributes failure only to a fixed
boundary: inventory resolution, credential-reference resolution, credential
retrieval, device-state collection, or live safety validation. Provider and
device exception strings, response bodies, command output, and secret material
remain suppressed from typed evidence and process output. This attribution does
not change outcome semantics, the version 1 `ChangeRecord` schema, stale-plan
checks, or execution and recovery behavior. Live device-write acceptance remains
pending.

Retry #2 passed inventory and credential retrieval, then blocked during device
state collection before execution. Read-only diagnosis found that neither
repository-pinned collection (`ansible.netcommon` 8.6.0 and `cisco.ios` 11.4.2)
was present in the deployment runtime's effective search path. This was a
deployment-runtime dependency defect, not a plan, inventory, OpenBao, or device
write failure. The pre-JWT runtime check now fails closed with one sanitized
message when requirements, search paths, installed metadata, or exact versions
are unavailable.

Retry #3 subsequently completed the protected deployment with `SUCCEEDED` typed
evidence. Independent read-only verification confirmed the exact desired
description on GigabitEthernet2, retained protection of the GigabitEthernet1
management interface, and no need for recovery. The successful execution also
exposed a control-plane gap: after a local macOS permission failure, Buildkite
could retry the failed `deploy-gate` job inside the already-approved build.

The deployment command step therefore disables both automatic and manual retry.
As defense in depth, `deployment_gate.sh` accepts only
`BUILDKITE_RETRY_COUNT=0` (with absence treated as zero for local compatibility)
and rejects every retried or malformed value before commit verification, either
OIDC request, promotion authorization, runtime verification, or any
NetBox/OpenBao/device boundary. This prohibits same-build `deploy-gate` replay.
Another Buildkite build is a distinct authorization context and requires another
human approval; normal NCDP operating procedure also requires an explicit
commit-bound retry marker for an intentional retry. Pipeline-wide Buildkite
Rebuild disablement is not part of the accepted 7C step-level control.

Increment 7C is complete. Protected-main build #46 produced `SUCCEEDED` typed
evidence for the exact single-device plan, and independent read-only verification
confirmed the desired GigabitEthernet2 state and GigabitEthernet1 management
safety. The single-attempt retry hardening then merged, and protected-main build
#48 accepted the unchanged-request no-write path without privileged credential
or device access. The complete evidence and scope boundaries are recorded in the
[Increment 7C acceptance report](../acceptance/buildkite-live-deployment-increment-7c.md).
