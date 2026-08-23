# ADR 0009: Buildkite promotion boundary

Status: accepted; Increment 7A complete

7A promotes only self-digested, offline artifacts. A promotion bundle binds the
exact Git commit, verified plan, policy, baseline, and PASSED assurance record.
The deployment gate verifies those bindings and explicit human-entered digests;
it performs no deployment. Buildkite environment metadata is not identity proof.
OIDC federation to OpenBao and live enforced execution remain 7B/7C work. The
external main-branch protection prerequisite was satisfied during Increment 7A
acceptance; Buildkite environment metadata remains non-cryptographic and is not
workload identity proof.
