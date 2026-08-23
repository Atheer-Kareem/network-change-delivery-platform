# ADR 0009: Buildkite promotion boundary

Status: accepted; Increment 7A complete

7A promotes only self-digested, offline artifacts. A promotion bundle binds the
exact Git commit, verified plan, policy, baseline, and PASSED assurance record.
The deployment gate verifies those bindings and explicit human-entered digests;
it performs no deployment. Buildkite environment metadata is not identity proof.
OIDC federation to OpenBao was subsequently accepted in Increment 7B; live
enforced execution remains Increment 7C work. The
external main-branch protection prerequisite was satisfied during Increment 7A
acceptance; Buildkite environment metadata remains non-cryptographic and is not
workload identity proof.

The active approval UX was subsequently refined without removing the human
boundary. After successful artifact upload, promotion records its three
repository-verified digests as machine-generated `promoted-*` build metadata. A
fieldless Buildkite block is the explicit human authorization event. The gate
still depends on that block, independently verifies the downloaded promotion,
and requires exact agreement with the recorded values. Automatic metadata is
evidence, not approval, and the system no longer claims that the human
independently transcribes or cryptographically compares the digests.
