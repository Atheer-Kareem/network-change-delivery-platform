# Junos transactional execution boundary

**Status:** Accepted

**Date:** 2026-08-22

## Context

Increment 4 requires policy to inspect and approve the exact Junos candidate
after load and commit-check but before `commit confirmed 5`. Investigation of
`juniper.device.config` 2.0.2 showed that each module invocation closes and
discards its candidate database before returning. A separate invocation would
therefore reload a second candidate that Python had not approved.

Relaxing pre-commit validation was rejected because unrelated shared-candidate
changes could become active. Private mode does not solve the post-return approval
gap. A custom Runner module or action plugin was rejected as unnecessary
complexity that would duplicate PyEZ and blur policy/provider ownership.

## Decision

Cisco IOS XE configuration remains executed through Ansible Runner and
`cisco.ios`. Junos transactional configuration uses a narrow direct-PyEZ adapter
under the platform Python control layer. One `Device` session and one
`Config(mode="exclusive")` context remain open across initial clean-candidate
verification, deterministic XML merge, commit-check, semantic candidate and diff
validation, and `commit(confirm=5)`.

The transaction adapter exposes bounded phases; Python retains the decision to
commit, independently validate using a fresh session, and confirm using another
fresh session. Vendor-specific execution behind common platform contracts is
intentional and preserves honest native semantics.

This decision supersedes only ADR-0002's Junos execution-provider detail. Its
control-plane ownership, Cisco Runner boundary, and other architecture decisions
remain in force.

## Consequences

The direct runtime dependency is `junos-eznc`; an unused `juniper.device`
collection is not installed. The adapter must disable SSH key, agent, SSH-config
proxy, and endpoint fallback, and must require the operator-established exact
`[host]:830` known-hosts entry. Pre-commit failures discard only NCDP's still
uncommitted candidate with rollback 0. No rollback 1, blind retry, or confirmation
after an ambiguous commit is permitted.
