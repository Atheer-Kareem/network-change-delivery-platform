# Product scope and reference-environment boundary

**Status:** Accepted

**Date:** 2026-08-21

## Context

A portfolio and internal demonstration needs to show realistic, safety-focused
NetDevOps delivery without company infrastructure or coupling to an earlier
repository whose V1.5 production implementation is paused.

## Decision

Build a greenfield reference platform for Cisco IOS/IOS XE and Junos in a
personal MacBook and CML mini-PC lab. It serves internal demonstration and public
portfolio purposes. Company data is forbidden. `network-automation-platform`
V1.0.0 and its V1.5 architecture baseline and CAT 8000V/NETCONF feasibility are
complete; V1.5 production implementation is paused and has not started. The
projects remain separate: this repository does not modify, depend on, or copy
the earlier one. Fortinet is deferred.

Explicit non-goals include production use; Kubernetes, NSO, and initial Nornir;
autonomous or self-healing writes; arbitrary PR-supplied commands; universal
vendor parity or transaction semantics; automatic fallback or ambiguous-write
retry; fleet atomicity; HA; generic plugins; and production-readiness claims.

## Rationale

A constrained greenfield system can demonstrate sound boundaries and evidence
without inheriting compatibility debt or exposing proprietary information.

## Consequences

All examples and tests use synthetic lab data. Vendor differences remain visible.
The project must earn capability incrementally and cannot claim production parity.

## Deferred decisions

Fortinet scope, production hardening, licensing, and broader vendor support.
