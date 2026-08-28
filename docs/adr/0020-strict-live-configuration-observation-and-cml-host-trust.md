# ADR 0020: Strict live configuration observation and CML-anchored host trust

## Status

Accepted for Increment 10C-6.

ADR 0023 preserves strict host trust, readiness, and stable private chronology
while superseding Terraform ownership, fresh operator-twin creation, blanket
staging absence, and routine post-acceptance destroy as future live
prerequisites. Manual replacement requires re-onboarding and new trust.

## Decision

Real Oxidized observation uses SSH only. The pinned Oxidized 0.37.0 defaults of
`ssh, telnet` and `input.ssh.secure = false` are explicitly overridden with
`input.default = ssh`, debug disabled, and `input.ssh.secure = true`.
Consequently Net::SSH uses `verify_host_key: :always`; Telnet fallback, session
capture, and insecure changed-key acceptance are unavailable.

Each fresh CML realization requires a new, bounded host-trust enrollment.
`ssh-keyscan` is observation, not authentication: keys are accepted only after
Terraform ownership, exact lab and node UUIDs, expected label/platform/image,
BOOTED state, non-printing stored Day-0 hostname/address checks, legacy-lab
stoppage, and staging-lab absence are independently established. The dedicated
private `known_hosts` contains only the current `.14` and `.20` realization and
is mounted read-only at `/run/ncdp/home/.ssh`; the user's normal SSH directory is
never mounted.

Collection readiness schema 2 binds authorization to the SHA-256 digest of the
exact known-host bytes. The controller revalidates the private owner, mode,
regular-file, link-count, exact-node metadata, realization metadata, and digest
before every `node.next`. Missing, malformed, replaced, mismatched, or retired
trust fails closed. Destroying a realization invalidates readiness first and
retires its trust while preserving source identity and Git chronology.

One observation boundary joins the bounded `CollectionResult` to the existing
path-scoped `OxidizedRevision`. It resolves the target path before and after the
job, requires successful terminal job metadata, boundedly waits for Git
metadata, and applies a documented one-second tolerance for Oxidized-web's
whole-second timestamps plus a five-second Git serialization tolerance. It
never reads a blob or diff. An initial observation requires a revision;
identical later observations may correctly reuse the same commit and blob.
Repository HEAD is never substituted for node revision identity.

Oxidized 0.37.0 publishes terminal `node.last` metadata before its synchronous
`output.store` processing. A pre-existing identical path revision therefore
settles for the complete bounded metadata window before it is classified as
unchanged; a delayed changed path revision is accepted only after the same
chronology checks. The transient observation records a separate metadata-
settlement completion after that path-scoped decision. Durable observation
`completed_at` means this settlement boundary, not the earlier upstream
`node.last.end`; it is never earlier than either successful upstream completion
or the accepted Git storage timestamp. The existing five-second serialization
tolerance remains the only allowance for a new revision after upstream
completion.

Docker Desktop presents host bind mounts as root-owned inside its Linux VM even
when the container runs as UID/GID 501:20. Rugged/libgit2 therefore receives a
dedicated read-only Git config whose sole `safe.directory` entry is
`/var/lib/ncdp/config-history.git`. This narrowly resolves ownership validation;
the container remains non-root and the host repository remains mode 0700. The
real repository begins as a private empty directory because Oxidized/Rugged
must initialize the first writable bare repository itself.

The local operator Terraform root is destroyable under exact graph validation
and the sanitized UI, matching the fixed-address realization lifecycle. Trust
is retired before an exact 13-resource destroy, and independent CML, state, and
address absence are required before the branch may first be pushed.

## Consequences

The first Cisco and Junos observations create private baseline chronology, and
successful unchanged observations do not necessarily create new commits. Full
configuration remains only in the external private bare repository. No
configuration bytes, diffs, credentials, `ConfigurationObservationRecord`, or
`ChangeAuditRecord` cross this boundary. Protected pre/post correlation remains
Increment 10C-7 work; periodic collection, remotes, backup, and Git maintenance
remain disabled.
