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

After request validation, the gate obtains a second fresh Buildkite JWT using
the accepted audience, lifetime, and `pipeline_id` subject selection. It pipes
the JWT directly to `deploy-buildkite-promotion`. The command re-verifies the
promotion and request, creates `NetBoxInventoryProvider`, derives the
device-specific OpenBao role and credential path only from stable NetBox
identity, and calls `deploy_plan()` with the promoted plan digest as approval.
This preserves fresh inventory/device preflight, stale-plan checks,
vendor-specific execution and recovery, and independent post-write validation.

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
