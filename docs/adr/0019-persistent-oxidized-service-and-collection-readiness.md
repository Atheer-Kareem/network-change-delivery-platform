# ADR 0019: Persistent Oxidized service and fail-closed collection readiness

## Status

Accepted for Increment 10C-5; real-device collection remains disabled pending
the operator reboot gate and Increment 10C-6.

## Decision

The personal-lab Oxidized service is a user-owned macOS LaunchAgent whose
one-shot reconciler runs at login and every five minutes. Launchd alone owns
lifecycle; the Docker container has restart policy `no`. The reconciler is an
immutable wheel installation outside the checkout and records its source commit.
It never imports the active checkout.

The accepted Docker Desktop ownership model runs the container as the host
user's non-root UID/GID. A private host-owned bare repository is bind-mounted
directly and is both writable by Rugged and readable by the host metadata
reader. No `safe.directory`, archive bridge, root container, or broad filesystem
permission is used. The persistent repository identity and path remain those
from ADR 0018; an empty bare repository is not actual-state evidence.

Oxidized loads the exact two-node private JSONFile source with `interval: 0`,
one thread, zero retries, `next_adds_job: true`, and Git output. It cannot poll
autonomously. Its web listener may bind all container interfaces, but Docker
publishes port 8888 only on host `127.0.0.1`. That loopback boundary is critical
because oxidized-web also exposes configuration-returning endpoints. NCDP calls
only `/nodes.json` and the exact `node.next` route; it never calls fetch,
version-view, diff, or search endpoints.

Service availability is not collection authorization. A successful complete
NetBox/OpenBao refresh and verified two-node reload publishes a private
`collection-ready.json` marker for fifteen minutes. Refresh runs every five
minutes. Missing, stale, malformed, wrong-container, or wrong-population markers
block collection. Refresh failure removes readiness while the interval-zero
container may remain available for inspection. Changed source requires reload
before readiness. An ambiguous source publication invalidates readiness and
requires a later successful forced reload even if bytes subsequently compare
equal.

The persistent controller authenticates through `ncdp-oxidized-bootstrap`, a
machine AppRole whose only policy permits `update` on the exact SecretID issue
path for `ncdp-oxidized-source`. Its persistent SecretID has unlimited lifetime
and uses; this explicit personal-lab tradeoff is bounded by mode-0600 local
storage and the minimal issuer capability. Each refresh uses a one-use,
60-second issuer token to obtain a fresh bounded source SecretID in memory. No
admin token or direct device-read authority is available to the service.

Forced collection uses one private non-blocking lock per reviewed node. HTTP
200 and oxidized-web's `ok` mean submission only: `nodes.next` can return early
for a running node. Completion requires a new, temporally consistent
`last.start`, `last.end`, and status from `/nodes.json` before a hard deadline.
There is no retry. Concurrent, timed-out, failed, and inconsistent evidence is
reported with bounded classifications only.

## Consequences

The real source can be loaded safely while every node remains `never` and the
chronology has zero commits. The operator, not automation, performs the real Mac
reboot acceptance. Real collection, baseline commits, observation-record
publication, protected correlation, remotes/backups, and Git maintenance remain
later work.
