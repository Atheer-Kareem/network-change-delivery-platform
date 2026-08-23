# Threat model

## Protected assets and boundaries

Protected assets include reviewed intent, policy, commit and plan identity,
inventory truth, credentials, management access, device state, evidence,
configuration history, and telemetry integrity. Trust boundaries exist between
GitHub and Buildkite, PR validation and deployment, Buildkite and OpenBao,
control logic and providers, providers and devices, all integrations and the
evidence store, and the personal lab and any company environment.

## Threats and mitigations

| Threat | Primary mitigations |
| --- | --- |
| Malicious or accidental PR content | Unprivileged Zone 1, review, policy/schema tests, no write credentials or access, sanitized inputs |
| Secret exposure | OIDC-derived short-lived scoped credentials; no secrets in Git, models, logs, artifacts, or evidence |
| Unauthorized deployment | Protected commit binding, immutable plan digest, human approval, isolated deployment queue and identity |
| Stale approved plan | Fresh identity/state/necessity checks immediately before writes; fail closed |
| Target identity mismatch | Complete frozen resolution plus endpoint and device identity verification; no fallback |
| Compromised agent | Zone separation, minimal credentials, exact-artifact execution, short lifetimes, audit and rotation |
| Misconfigured agent | Explicit queue constraints, reproducible pinned containers, preflight, least privilege, fail-closed checks |
| Dependency tampering | Frozen lockfile, reviewed updates, immutable base-image digests, deterministic builds and later artifact provenance |
| Container-image tampering | Digest-pinned bases, recorded execution digest, controlled build/promotion, later signature/provenance verification |
| Unauthorized manual configuration | Oxidized chronology, desired/live comparison, monitoring, investigation before remediation |
| False or incomplete evidence | Typed required records, correlation IDs and digests, independent validation, append-oriented storage and completeness checks |
| Ambiguous write outcome | No automatic retry; observe and classify before vendor-aware recovery |
| Overlapping fleet changes | Target-set intersection detection with serialization or rejection |
| Monitoring failure | Independent monitoring health and alerting; pipeline completion never implies continued health |
| Source-of-truth inconsistency | Explicit Git/NetBox/device authority split, snapshots, freshness checks, blocking contradictions |

## Residual risks and lab limitations

Provider and device defects, stolen administrator identities, supply-chain
compromise, incomplete vendor telemetry, and simultaneous out-of-band changes
cannot be eliminated. Vendor transaction strength differs, and no multi-device
atomicity is claimed. Recovery itself can fail.

The personal lab may place logical zones on one MacBook and a CML mini-PC. This
does not reproduce production network segmentation, hardware roots of trust,
high availability, enterprise identity governance, scale, or operational staffing.
The reference implementation must not be promoted to production unchanged.
## Buildkite deployment-boundary residual risks

7A established protected-main promotion acceptance. Protected-main build #26
then established the 7B cryptographic Buildkite/OpenBao identity boundary,
including signature and constrained-role validation, exact runtime metadata
comparison, and a token with zero effective policy. The personal-lab agent and
OpenBao may still share one host, so this is not production-grade isolation. The
7B token deliberately has no secret-read policy. The unaccepted 7C-A foundation
uses a distinct single-device role, one exact read policy, one token use, and a
commit-changed request bound to the promoted plan. A compromised eligible
deployment job remains a high-impact boundary; short leases, exact runtime
identity, fresh preflight, and vendor-aware recovery reduce but do not eliminate
that risk. Promotion artifacts contain no credentials. No fleet-wide atomicity
is claimed.
