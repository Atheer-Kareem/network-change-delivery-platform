# ADR 0018: Private Git chronology for observed configuration state

## Status

Accepted for Increment 10C-4.

## Context

Observed device configurations need an independent chronology without making
Oxidized desired-state, deployment, rollback, inventory, or credential
authority. Full configurations are sensitive and cannot enter the public
product repository, Buildkite evidence, or NCDP audit records. Correlation needs
stable, path-specific Git metadata even when another node advances repository
HEAD or an unchanged observation creates no commit.

## Decision

Oxidized alone writes one private local bare Rugged/libgit2 repository using
`single_repo: true`. Its stable NCDP identity is
`oxidized:ncdp-lab-actual-state`; the personal-lab persistent path is
`/Users/netdevops/.local/state/ncdp/oxidized/config-history.git`. The author is
`NCDP Oxidized` with non-personal local email `oxidized@ncdp.local`. Group
`managed` produces paths `managed/netbox-device-1` and
`managed/netbox-device-2`.

The repository has no remote, automatic push, GitHub hook, or working tree.
`type_as_directory` and `clean_obsolete_nodes` remain disabled. The bare index
written by Oxidized is expected. Normal Git hooks are not an execution boundary
for Rugged commits.

NCDP reads metadata only through a bounded Git CLI adapter. It validates the
private external bare repository, local object database, absence of remotes,
alternates, and replacement refs, then locates the newest commit affecting the
exact group/node path. It resolves that commit's normal blob entry without
reading blob bytes and constructs the existing `OxidizedRevision`. Repository
HEAD is not treated as every node's latest revision.

`OxidizedRevision.collected_at` is the UTC-normalized commit timestamp at which
Oxidized stored the observation. It is not a device-clock time, exact transport
completion time, deployment boundary, or proof of causality. Identical bytes
produce no commit; therefore unchanged observation evidence reuses the prior
path revision.

## Consequences

Full configuration bytes remain exclusively in private Git. NCDP exposes only
repository identity, canonical path, commit OID, blob OID, and storage
timestamp. The 10C-4 acceptance uses Oxidized 0.37.0's real public Git-output
store against a disposable private repository; it never creates or populates
the future persistent path. Container-owned tmpfs and local archive extraction
are synthetic-test plumbing only and do not freeze the 10C-5 service UID/GID
model.

Persistent service ownership, device collection, scheduling, forced control,
observation-record publication, remote backup, pushes, and automatic garbage
collection remain out of scope. Offline Git maintenance requires a stopped
writer and a reviewed backup/recovery procedure and remains future operational
hardening.
