# Buildkite protected live deployment

The accepted 7C boundary provides fail-closed, single-device protected delivery
without changing the vendor execution lifecycle. Every eligible protected-main
build performs the accepted zero-policy 7B identity exchange and exact
promotion verification. The gate then checks whether that exact commit changed
the fixed live request relative to its first parent. Authorization reads the
bounded regular blob directly from that commit's Git object; working-tree
creation, modification, deletion, symlinks, and oversized content cannot
substitute request semantics.

After the visible validation barrier, disposable CML staging and first-class
Batfish assurance are independent protected-main prerequisites. Immutable
promotion waits for both, downloads assurance from the exact same-build
`batfish-assurance` step, and independently verifies it before creating the
bundle. Human authorization remains between promotion and the serialized,
non-retriable `deploy-gate`.

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

Increment 10B-2 requires an external, private `NCDP_AUDIT_STORE_ROOT` and
validates `AuditStore`, the exact promotion, and same-build sanitized staging
evidence before obtaining the second device-capable JWT or allowing a write.
For an unchanged live request, the approved no-write path durably publishes the
plan, assurance record, promotion manifest, staging evidence, and a `NO_WRITE`
audit envelope before succeeding. A real execution additionally publishes the
semantically plan-bound `ChangeRecord`; the envelope is always published last.

Audit storage is a separate failure domain from device execution. If durable
publication fails after a known device outcome, the job fails and reports that
audit failure without retrying deployment, issuing an inverse, invoking native
recovery, or otherwise causing another device transaction. If deployment also
failed or was ambiguous, its typed outcome remains primary and both failures
are reported. If execution fails before a typed `ChangeRecord` exists, the gate
does not fabricate a durable execution audit record.

Increment 10C-7 adds metadata-only configuration bracketing inside the same
no-retry deploy-gate job. After all existing authorization checks, a successful
PRE observation is required before the device command. POST is attempted as
soon as that command returns, including on a nonzero result. Canonical private
attempt files exist only below the job temporary directory. After typed
ChangeRecord handling, the immutable parent audit is persisted first; only a
verified parent permits append-only `ConfigurationObservationRecord`
persistence. Metadata failure never retries or rolls back the device attempt,
and the original device outcome remains primary. Protected PRE/write/POST
correlation is accepted; chronology remains temporal bracketing rather than
proof that the protected write caused the observed revision.

## Historical protected-deployment acceptance evolution

The acceptance history is retained because its failures demonstrate the
fail-closed and no-retry contracts; it is not the current implementation status:

- Builds #150, #152, #154, and #156 each stopped at a distinct pre-write or
  evidence boundary. None was retried. Corrections used a new commit, build,
  request authorization, and fresh preparation.
- Build #158 accepted the CML-anchored trust and protected Cisco
  PRE/write/POST correlation path, including immutable parent/child evidence.
- The earlier 7C sequence likewise retained its blocked attempts rather than
  replaying them. Its accepted `SUCCEEDED` single-device execution and later
  unchanged-request no-write acceptance are recorded as Builds #46 and #48 in
  the cumulative acceptance record.
- Later protected SNMP provisioning accepted Cisco Build #267 and Junos Build
  #275 without weakening the same authorization and non-retry boundaries.

The detailed causes, corrective commits, evidence, and exact scope are preserved
in the
[Increment 7C acceptance report](../acceptance/buildkite-live-deployment-increment-7c.md),
the
[Increment 10C-7B acceptance report](../acceptance/protected-configuration-observation-increment-10c7b.md),
and the
[Increment 11C acceptance report](../acceptance/continuous-observability-increment-11c.md).

The current accepted boundary supports one promoted `DeploymentPlan`;
Buildkite fleet deployment remains unsupported. NetBox access is
inventory-read-only, NCDP performs no NetBox mutation, same-build deploy-gate
replay is prohibited, and an intentional corrected attempt requires a fresh
commit, build, request authorization, and human approval.
