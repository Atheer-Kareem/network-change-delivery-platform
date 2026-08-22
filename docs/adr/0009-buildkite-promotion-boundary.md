# ADR 0009: Buildkite promotion boundary

Status: accepted for Increment 7A review

7A promotes only self-digested, offline artifacts. A promotion bundle binds the
exact Git commit, verified plan, policy, baseline, and PASSED assurance record.
The deployment gate verifies those bindings and explicit human-entered digests;
it performs no deployment. Buildkite environment metadata is not identity proof.
OIDC federation to OpenBao, protected-branch enforcement, and live execution
remain 7B/7C work. Main branch protection is an external prerequisite.
