# Batfish assurance

Increment 6A adds an offline assurance boundary. A snapshot contains only
`configs/` files. Python validates and hashes the snapshot, sends it to the
explicit Batfish provider, normalizes observations, and applies the typed
policy. Raw Batfish objects never enter platform models or evidence.

The committed service is `batfish/batfish:test-2026.07.20.3565` on loopback
port 9996 with the arm64 manifest digest
`sha256:0c2ea3fc2f90cac6b9339936da435ac9916d0ad3308bebbe5df13b1a0cf49819`;
the inspected multi-platform index is
`sha256:feaf749617d92a1ea5f95f54697d878ddb1c902a5bb515f1bb1741b516360966`.
Pybatfish is pinned in the lockfile.
Readiness is checked explicitly with a Pybatfish `Session`; ordinary unit tests
use injected providers and do not require Docker.

6A's generic subject digest is not yet bound to a deployment artifact. Exact
plan binding is Increment 6B, and runtime/Buildkite enforcement is later work.

Start and readiness gate:

```sh
docker compose -f compose.assurance.yaml up -d batfish
NCDP_BATFISH_HOST=127.0.0.1 uv run python -c 'from pybatfish.client.session import Session; Session(host="127.0.0.1", port=9996)'
docker compose -f compose.assurance.yaml down
```
