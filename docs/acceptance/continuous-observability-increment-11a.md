# Increment 11A management-service reachability acceptance

Status: implementation and offline/container acceptance prepared; live CML
acceptance pending a merged-main post-merge procedure.

## Offline and container contract

The implementation must prove without CML or device credentials:

* exact NetBox identities map through the existing inventory model to Cisco
  SSH TCP/22 and Junos NETCONF TCP/830;
* unsupported, missing, extra, duplicate, or changing populations fail closed;
* CML admission validates exact realization ownership while keeping UUIDs out of
  metric labels;
* file discovery publishes canonically and atomically under private filesystem
  controls;
* ACTIVE readiness binds generation, realization, exact two-node population,
  current containers, source commit, and freshness;
* retirement invalidates readiness and removes all live probe scheduling;
* synthetic reachable and unreachable TCP endpoints produce expected
  `probe_success` values;
* resulting `instance` values are stable NetBox identities rather than raw
  endpoints;
* TSDB survives reviewed container replacement and historical series survive
  target retirement;
* the container/image, loopback exposure, mount, privilege, and no-secret
  contracts pass inspection.

## PR staging attempt history

Natural PR Build #162 ran against commit
`0ff24fce3a17a20bc21d5115669f03a2f2506b95`; its CML staging job was
`01a0456a-4c6e-4384-94e5-3a8df602888b`. The exact 13-resource realization was
created successfully, and the START transition plan reported
`add=0 change=1 destroy=0` for only `module.twin.cml2_lifecycle.twin`.
Terraform began that lifecycle apply, but repeated sanitized
`CML2 Provider Error` diagnostics ended the provider/CML operation before
device readiness or NCDP validation was attempted. The available evidence does
not support a narrower provider or controller diagnosis.

Mandatory cleanup then passed the exact 13-resource destroy, independent CML
absence verification, and run-scoped Terraform state retirement. Build #162 is
not retried. This infrastructure failure is retained as implementation-PR
staging evidence and does not constitute 11A live acceptance.

## Post-merge live-attempt history

The first post-merge live-acceptance attempt used implementation commit
`f9a24abca1264c3657639ae2efe7b5fd1e9016fd` after natural merged-main Build
#164 passed. It stopped during persistent service installation with the bounded
failure `python: command not found`: the installer invoked a host `python`
alias instead of the exact versioned runtime interpreter it had already
created. No CML realization, device probe, device authentication or write,
OpenBao device-secret read, Oxidized mutation, or AuditStore mutation occurred.
The newly created partial first-install roots were inspected and safely removed.
Increment 11A live acceptance remains NOT YET PROVEN.

The second post-merge attempt used corrected implementation commit
`226d8b7101bdba702090bb0b9d66b31e6aa9d3f2` after natural merged-main Build
#166 passed. The corrected persistent installation, initial RETIRED
reconciliation, zero-target state, and TSDB initialization passed. The attempt
stopped before CML creation because the unqualified zero-OpenBao-read wording
conflicted with ADR 0013's accepted credential-bearing CML Day-0 bootstrap. No
device probe, device authentication or write, OpenBao device-secret read by the
observability plane, Oxidized mutation, or AuditStore mutation occurred.
Increment 11A live acceptance remains NOT YET PROVEN.

## Credential accounting boundary

The 11A observability plane performs zero OpenBao device-secret reads. This
boundary includes Prometheus, Blackbox Exporter, target materialization,
reconciliation, realization admission, Prometheus queries, Blackbox TCP probes,
readiness publication and verification, and target retirement. Those components
receive no device credential and perform no device authentication, CLI or RPC
command, configuration read, or device write.

ADR 0013 separately permits the operator CML infrastructure lifecycle to
retrieve the exact Cisco and Junos credentials freshly from OpenBao for its
minimum Day-0 management bootstrap. Those reads are infrastructure
initialization, not observability credential use or NCDP-managed intent. Final
evidence reports each operator-wrapper invocation separately, including its
bootstrap/source-login operations and the two reviewed device-secret
materializations performed by `_environment()`. Status evidence should use
credential-free CML, Terraform-state, or read-only inspection paths instead of
unnecessarily invoking that wrapper. Bootstrap values remain excluded from
Prometheus, Blackbox, metrics, labels, logs, and acceptance evidence.

## Pending live acceptance

After the implementation PR is merged, the operator must install/update the
repository-independent runtime from that exact commit without starting devices.
After independent staging/address collision admission, create a fresh exact
13-resource operator twin, transition it to STARTED, and prove the exact BOOTED
Cisco and Junos identities. Admit that realization, materialize the exact
NetBox-owned targets, and allow normal launchd reconciliation to publish fresh
readiness.

Live acceptance requires repeated successful TCP probes for
`netbox:dcim.device:1` on its derived SSH service and
`netbox:dcim.device:2` on its derived NETCONF service. Queries must prove stable
labels, no raw endpoint as `instance`, no CML UUID label, fresh realization and
container binding, interval reconciliation, and TSDB persistence. It must also
prove zero device authentication, commands, configuration reads and writes by
the observability plane; zero OpenBao device-secret reads by the observability
plane; zero Oxidized collections/history mutation; and zero AuditStore mutation.
ADR 0013 CML Day-0 bootstrap reads are permitted and accounted separately.

Before destroying the twin, invalidate readiness, retire admission, publish an
empty target generation, and prove no management probes remain scheduled.
Destroy the exact 13-resource graph, independently prove fixed-address absence,
and preserve historical Prometheus data. Only that complete evidence may mark:

`11A ACCEPTANCE: PASS`

This implementation PR does not claim live acceptance.
