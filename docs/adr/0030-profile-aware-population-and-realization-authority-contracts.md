# ADR 0030: Profile-aware population and realization authority contracts

- Status: Accepted
- Date: 2026-08-31

## Context

[ADR 0029](0029-profile-bound-read-only-inventory-and-transport-admission.md)
introduced a parallel read-only inventory and adapter without changing the v1
execution path. Its first provider admission reused `ncdp-managed`, but that tag
already has accepted legacy meaning: exactly `core-02` and `edge-junos-01` feed
v1 inventory, observability, Oxidized, fleet, SNMP, and protected delivery.
Classic IOS cannot safely join that population because v1 `InventoryDevice`
admits only IOS XE and Junos.

B3 also needs a future four-device realization and strict host trust without
making a STAGING management endpoint generally selectable. Defining those
contracts before external authority migration prevents B3 tooling from
inventing identity, endpoint, or trust semantics while mutating NetBox, CML, or
OpenBao.

## Decision

- `ncdp-managed` retains its legacy exact-two meaning and behavior.
- `ncdp-profiled-inventory` separately means eligibility for reviewed
  profile-aware inventory and realization. It grants no credential, SNMP,
  deployment, or protected-write authority.
- Git owns one closed four-member catalog of stable logical names, expected
  roles, factual platform/device-type pairs, network OS, automation profiles,
  and CML realization profiles. NetBox will later own each allocated stable
  device ID and the factual tag, role, platform, type, interface, and IP
  relationships.
- The profiled provider uses only `ncdp-profiled-inventory`. Its population
  resolver requires exactly `core-02`, `edge-junos-01`, `transit-ios-01`, and
  `access-sw-01`, in deterministic catalog order, with exact Git-approved
  metadata. Per-device resolution is limited to those same names and compares
  independently resolved NetBox facts with that name's catalog member. Neither
  path has a legacy-tag fallback.
- Normal targeting remains `ProfiledInventoryDevice.live_read_only_target()`.
  `ProfiledInventoryDevice` has no STAGING method and no generic purpose
  selector.
- Additive, secret-free realization contracts bind stable NetBox identity,
  exact profile identity, CML lab/node identity, purpose-bound management
  identity, lifecycle/freshness, and durable evidence references. They perform
  no CML operation and are not imported by current runtimes.
- Generic host-trust metadata binds an SSH fingerprint to the exact CML lab and
  node, stable NetBox device, logical name, management endpoint, profiles,
  CML-anchor evidence, and trust generation. Network-visible key discovery
  alone is never authority. Normal evidence contains no public-key blob.
- Only an exact, fresh, `READY`, run-scoped `StagingRealizationContext` may
  project a STAGING read-only target. It must exactly equal the device's
  NetBox-owned STAGING IP and management-interface binding. It cannot call the
  LIVE projection, accept a purpose argument, infer from `primary_ip4`, or
  fall back.

The future NetBox IDs of `transit-ios-01` and `access-sw-01` are deliberately
absent from Git. B3-1 allocates no address and creates no external object.

## Current environment relationship

[ADR 0024](0024-two-router-live-and-ephemeral-staging.md) remains current
environment truth. The persistent CML lab, legacy observability, and Oxidized
remain exact-two. B3-1 does not import its contracts into current inventory,
deployment, fleet, promotion, Buildkite, Terraform, staging, observability,
SNMP, or Oxidized code.

A future accepted four-device reference-environment decision will supersede ADR
0024 only after separately reviewed NetBox identity, CML realization, OpenBao
credential, CML-anchored trust, LIVE/STAGING read-only acceptance, and rollback
evidence exist. No four-device environment is claimed here.

## Consequences

B3 can migrate external authorities in bounded increments without colliding
with the v1 tag or allowing classic IOS into v1 schemas. Stable logical names
and profile pairings are reviewable before NetBox assigns new IDs. STAGING
targeting becomes structurally dependent on exact disposable-realization
authority instead of a caller-controlled endpoint switch.

Private rendering material needed for a future canonical `known_hosts` file is
deferred to B3-4. Fingerprints and anchor references alone do not pretend to be
renderable trust material. CML reconciliation, trust enrollment, NetBox and
OpenBao mutation, four-node Terraform staging, observability migration, and any
device access remain later increments.
