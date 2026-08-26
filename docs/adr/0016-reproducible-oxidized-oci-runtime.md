# ADR 0016: Reproducible Oxidized OCI runtime

## Status

Accepted for Increment 10C-2.

## Context

The observed-state chronology selected for Increment 10C requires Oxidized and
oxidized-web. The macOS system Ruby is host-dependent and does not provide a
reviewable Linux/Apple-Silicon runtime contract. The upstream container is a
useful implementation reference, but its current build installs oxidized-web
without independently freezing the complete Oxidized/oxidized-web dependency
pair. A moving upstream image is therefore not the project's dependency lock.

Increment 10C-2 must prove packaging and a synthetic API only. NetBox inventory,
OpenBao credentials, actual device collection, private Git chronology,
persistent service ownership, and observation control remain separate reviews.

## Decision

NCDP owns a narrow OCI build context at `infrastructure/oxidized/runtime/`.
It freezes Oxidized 0.37.0, oxidized-web 0.18.1, Ruby 3.3.9, Bundler 2.5.22,
and the complete Bundler lock, including Rugged 1.9.6. The base is
`ruby:3.3.9-slim-bookworm` pinned to registry index digest
`sha256:b084aa6c608f29f4a3b54577884bb7e983abd0852c3650e7ab03f9b46f87151e`.
The verified Linux arm64 child digest is
`sha256:81337ce300c74cbcd2eb826d902b286f1ca3c5b64fb22eb632403be9eab12f86`.
Registry index and platform-manifest digests are distinct from a local built
image ID.

The multi-stage image retains only runtime libraries and runs by default as the
fixed non-root UID/GID `30000:30000`. This stable default is sufficient for the
packaging proof; host bind-mount ownership and any caller-selected identity are
deferred to the persistent-service review. The normal entrypoint is Oxidized,
without a supervisor.

Synthetic acceptance uses one documentation-only TEST-NET node, interval zero,
and no collection request. Oxidized-web listens on the container interface while
Docker publishes the dynamic host port only on `127.0.0.1`. Acceptance requires
`GET /nodes.json` to report status `never`, no configuration output, a read-only
root filesystem, dropped capabilities, no host networking or Docker socket, and
no repository or authority-service mounts or environment.

## Consequences

The runtime can be rebuilt and inspected on Apple Silicon without relying on
the host Ruby or an unfrozen gem install. Compiler dependencies and package
caches do not enter the final stage. A local image ID proves the accepted local
build only; publishing and pinning a portable project image is deliberately a
later runtime-ownership concern.

This decision creates no inventory, credentials, device configuration,
configuration-history repository, scheduler, forced collection controller, or
persistent service. Oxidized remains observed-state chronology and receives no
delivery or rollback authority.
