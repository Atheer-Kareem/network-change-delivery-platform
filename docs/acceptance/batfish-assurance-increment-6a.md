# Batfish assurance foundation — Increment 6A

Increment 6A is an offline foundation. Its fixtures are synthetic and contain
three logical nodes: `core-02`, `edge-junos-01`, and `core-03`. Static routed
links form `core-02 — edge-junos-01 — core-03`; loopbacks provide a critical
end-to-end flow from `10.6.2.2` to `10.6.3.3`.

The baseline and behavior-preserving candidate differ only in descriptions.
The disruptive candidate shuts the sole core-02 transit interface. Unit tests
exercise manifests, bounded errors, policy, evidence secrecy, and report
reservation using fakes. Explicit Batfish integration is opt-in and is not part
of ordinary pytest.

Increment 6A does not contact devices, NetBox, OpenBao, company systems, or
deployment systems. Increment 6B will bind assurance to exact NCDP plans.

## Local Batfish acceptance

The disposable service was started from `compose.assurance.yaml` on loopback
only (`127.0.0.1:9996`). PyBatfish established a session and reported service
version `2026.07.20.3565`. The baseline and good candidate each parsed all
three files with zero initialization issues; the critical `core-02` flow to
`10.6.3.3` was reachable in both snapshots and differential reachability
reported `0` changed rows, producing `PASSED` (CLI exit 0). The disruptive
candidate also parsed cleanly with zero initialization issues, but the critical
flow became unreachable and differential reachability reported `1` changed row,
producing `FAILED` (CLI exit 2). The service was disposable and was not used by
ordinary unit tests.

Evidence is platform-owned bounded JSON: raw configurations, traces, parser
stacks, and full Batfish answer tables are not retained.
