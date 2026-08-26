# ADR 0015: Append-only configuration observation records

## Status

Accepted. This decision extends the audit architecture from Increment 10A and
the append-only persistence contract from Increment 10B without changing their
existing schemas or authority boundaries.

## Context

`ChangeAuditRecord` schema 1 is an immutable, digest-bound envelope for one
reviewed delivery attempt. Durable schema-1 records already exist under
`records/<record-id>.json`. Their canonical bytes, digest meaning, artifact
kinds, and delivery semantics cannot be changed to attach evidence collected
later.

Oxidized configuration observations may happen before or after delivery, may
observe no change, and may complete after the delivery audit record has already
been published. Full device configurations are potentially sensitive and
belong only in a future private external Oxidized Git repository. Periodic
polling and independent operator changes also mean temporal evidence cannot
prove that an NCDP attempt exclusively caused an observed revision.

## Decision

Increment 10C-1 introduces a separate immutable
`ConfigurationObservationRecord` schema 1. It is follow-up correlation
metadata, not delivery or device-execution evidence. It contains:

- its UUID, UTC generation time, canonical SHA-256 digest, and schema version;
- the exact parent `ChangeAuditRecord` UUID and digest;
- one bounded external repository identity, stable NetBox device identity,
  canonical Oxidized node, and optional canonical group;
- at least one typed pre- or post-observation attempt;
- metadata-only Git commit, path, blob, and collection-time revisions;
- a closed observation status and sanitized failure category;
- a bounded temporal relationship, aggregate status, and schema-1 causality
  fixed to `NOT_PROVEN`.

Operational source, node, authentication, connection, collection, output, and
history failures map only to `FAILED`; collection timeout maps only to
`TIMED_OUT`; and concurrent collection or inconsistent evidence maps only to
`AMBIGUOUS`. Successful statuses carry no failure category.

Observation records are published separately at
`observation-records/<observation-record-id>.json`. Publication first reads the
parent through the existing validated `AuditStore`, proves both parent UUID and
digest, and proves that the observed stable device is one of the parent's
targets. The parent is never rewritten. Multiple immutable observation records
may reference one parent.

The new store reuses the reviewed private-root validation, no-follow reads,
mode and owner checks, canonical JSON, exclusive same-directory temporary-file
publication, hard-link no-replace behavior, and `fsync` durability machinery.
It remains a typed store, not a generic object database. Direct reads and
bounded deterministic scans revalidate record integrity and the parent link.

`ChangeAuditRecord` remains schema 1. Its seven `AuditArtifactKind` values,
`records/` namespace, artifact namespace, canonical digest, and existing CLI
queries remain unchanged. Configuration observations are not audit artifacts.

## Consequences

Later observed-state evidence can be durably linked to an already published
delivery audit without rewriting history or duplicating the delivery envelope.
The record may state that revisions were observed before or after an NCDP
attempt and whether their object identities changed. It may never claim that
NCDP caused the change. Oxidized cannot authorize deployment, recovery, or
rollback, and its private Git chronology is not desired-state authority.

`TEMPORALLY_BRACKETED` means the future controller established an ordered pre-
and post-observation window around the parent NCDP attempt. The record validates
that the pre-observation completed before the post-observation was requested;
it does not compare that window to `ChangeAuditRecord.generated_at`, because
envelope generation time is not a trustworthy device-execution boundary. The
controller contract and schema-1 `NOT_PROVEN` causality limitation remain part
of interpreting this relationship.

Configuration bytes, diffs, raw device/API output, credentials, tokens,
passwords, and free-form errors are excluded from the schema. Oxidized
installation, runtime packaging, private Git creation, inventory and credential
materialization, scheduling, API control, and protected pre/post collection
remain future Increment 10C work.
