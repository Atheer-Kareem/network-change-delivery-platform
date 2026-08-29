# ADR 0011: Buildkite protected live-deployment boundary

## Status

Accepted. External live deployment completed in Increment 7C through Build
#46; the no-retry hardening was accepted through Build #48.

## Decision

The accepted zero-policy role `ncdp-buildkite-deploy` remains the ordinary-main
workload identity check. Live CML deployment uses a separate role and policy per
stable NetBox device ID. Device 1 uses role
`ncdp-buildkite-cml-deploy-device-1` and policy
`ncdp-buildkite-cml-device-1-read`. The policy grants only `read` on
`ncdp/data/devices/1/ssh`; it grants no list, write, deletion, auth-management,
sys-management, or other-path capability.

The privileged role preserves the accepted issuer, audience, immutable `sub`
subject, `main` branch, `deploy-gate` step, and mapped pipeline, commit, branch,
step, and job constraints. It issues a no-default-policy, maximum 300-second,
single-use token with exactly the corresponding device-read policy. NCDP
requires exact token, Identity-derived, aggregate, and external-namespace policy
results before consuming that one use on the exact KV-v2 credential GET.

A write is eligible only when the current protected-main commit changes the
fixed `deployments/live/request.yaml` path relative to its first parent, the file
exists as a bounded regular blob in that exact commit, its strict committed
contents bind the promoted single-device plan's change ID, digest, and stable
inventory identity, and the human promotion approval and accepted 7B identity
gate have passed. Mutable working-tree contents do not authorize a write. Target
hostname and arbitrary secret path cannot select privilege. A second fresh JWT
enters the dedicated deployment CLI through stdin and is never stored in a shell
variable or file.

The CLI verifies the promotion and request again, requires NetBox inventory and
OpenBao provenance, creates the read-only NetBox provider and one-use OIDC secret
provider, and delegates execution to the existing `deploy_plan()` lifecycle. It
writes one mode-0600 `ChangeRecord` and succeeds only for existing successful or
recovered outcomes. The shell uploads a produced record for both zero and
nonzero outcomes before preserving the deployment status; it never fabricates a
record for a pre-evidence failure. Fleet promotion is rejected; one token use
maps to one exact credential read for the first protected acceptance.

## Consequences

Ordinary main builds remain no-write and stop before privileged JWT issuance,
NetBox access, credential retrieval, or device access. NetBox remains read-only,
and OpenBao remains the credential system of record. The accepted 7B role is not
repurposed or broadened. At the 7C-A implementation boundary there was no active
request or live write; the later 7C-B request and protected-main exercise owned
external live CML acceptance. No fleet-wide atomicity or production-grade host
isolation is claimed.

7C-B1 prepared that acceptance with one repository-owned, single-device
promotion input for `core-02`. Its immutable plan originated from fresh
read-only NetBox resolution, one exact OpenBao credential read, and read-only
device collection. The dedicated Batfish baseline is sanitized and plan-bound;
it models the selected interface's exact observed description but is not claimed
as a fresh full device or production twin. The B1 change contained no live
request, so protected main validated the promotion in no-write mode before the
separate reviewed deployment request exercised live acceptance.

Build #46 then completed the exact commit-bound single-device deployment,
independent post-validation, and typed evidence path. Build #48 verified the
hardened unchanged-request `NO_WRITE` path. The chronological acceptance and
failure-driven hardening evidence remains in the Increment 7C acceptance
record.
