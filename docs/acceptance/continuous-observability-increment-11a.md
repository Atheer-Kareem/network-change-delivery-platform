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
prove zero device authentication/commands/writes, zero OpenBao device-secret
reads, zero Oxidized collections/history mutation, and zero AuditStore mutation.

Before destroying the twin, invalidate readiness, retire admission, publish an
empty target generation, and prove no management probes remain scheduled.
Destroy the exact 13-resource graph, independently prove fixed-address absence,
and preserve historical Prometheus data. Only that complete evidence may mark:

`11A ACCEPTANCE: PASS`

This implementation PR does not claim live acceptance.
