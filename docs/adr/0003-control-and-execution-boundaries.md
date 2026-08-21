# Python control plane with vendor-aware execution providers

**Status:** Accepted

**Date:** 2026-08-21

## Context

Common fleet policy and differing vendor transaction mechanisms must coexist
without pushing policy into an automation tool or inventing false portability.

## Decision

Python owns validation, policy, target resolution, planning, risk, fleet rollout,
evidence, recovery decisions, and provider composition. Ansible is an execution
provider. Cisco and Juniper providers may use distinct native safety mechanisms.
Common intent is modeled only where semantics are honestly common; there is no
lowest-common-denominator vendor abstraction and no generic dynamic plugin
framework. Nornir is deferred, not rejected.

## Rationale

Stable product policy should not depend on provider mechanics. Honest vendor
differences enable stronger safety than a universal command abstraction.

## Consequences

Provider interfaces stay explicit and narrow. Validation and recovery may differ
by platform while returning platform-owned results. New providers require a
deliberate architecture decision rather than runtime discovery.

## Deferred decisions

Provider protocols, concrete Ansible content, result schemas, and whether later
evidence supports a Nornir-based path.
