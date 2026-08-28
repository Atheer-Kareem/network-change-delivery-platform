# Phase B2: OpenBao staging credential isolation acceptance

Status: external OpenBao authority complete; repository evidence pending review.

## Authority and scope

ADR 0023 and merged main
`661857ebf3d67c5ba7c4fe9511f74ed26ff3fe17`, validated by natural Buildkite
Build #183, authorize this bounded OpenBao-only increment. NetBox devices 1 and
2 remain the canonical live pair. B1-2 established devices 6 `stg-core-02` and
7 `stg-edge-junos-01` as their persistent staging homologs.

B2 changed standing OpenBao staging credential authority from live device IDs
1/2 to staging device IDs 6/7. It did not migrate the staging runtime consumer.
No CML staging execution is authorized until the protected B3/B4 migration is
complete.

## Recovery chronology

B2 completed across an interrupted creation attempt and a bounded recovery:

1. The first trusted operator process created secrets, policies, and JWT roles
   for devices 6 and 7 and read them back successfully.
2. A restricted verification token carrying only policy 6 and no default policy
   then received HTTP 403 from `POST /v1/sys/capabilities-self`. The request
   tested access to the system introspection endpoint, not a device-secret path.
   OpenBao's default policy grants that endpoint, so omitting the default policy
   made the chosen self-introspection mechanism unavailable. The token was
   revoked, and no legacy object was retired.
3. Recovery independently revalidated the retained objects, exact policy and
   role definitions, secret key sets and versions, credential separation, and
   absence of the earlier verification token.
4. The first administrative-side capability check used the supported
   `POST /v1/sys/capabilities` endpoint but a local guard expected a nested
   response field. It stopped before retirement and revoked its token. A
   sanitized response-shape check established that OpenBao 2.6.2 returns the
   path matrix directly in `data`.
5. The corrected guard proved both exact matrices without reading secret
   payloads. Both temporary tokens were revoked and became unusable.
6. Only then were the two historical staging roles and two historical staging
   policies for live devices 1/2 deleted in a checked sequence.

No valid secret, policy, or role for devices 6/7 was deleted, recreated, or
rewritten during recovery. No automatic rollback occurred.

## Retained staging credential authority

Both KV-v2 secrets have version 1 and exactly the keys `username` and
`password`:

| NetBox device | Logical reference | Created (UTC) |
| ---: | --- | --- |
| 6 | `openbao:kv-v2:ncdp/devices/6/ssh` | `2026-08-28T07:39:14.660596262Z` |
| 7 | `openbao:kv-v2:ncdp/devices/7/ssh` | `2026-08-28T07:39:14.662927387Z` |

The trusted process generated independent 48-character credentials from a
cryptographically secure source using the Day-0-safe ASCII alphanumeric
alphabet. In-memory comparisons, emitting booleans only, proved that device 6
differs from device 7 and that each differs from both live device credentials.
No credential value or derived secret hash entered evidence.

The standing policies are exactly:

```hcl
path "ncdp/data/devices/6/ssh" {
  capabilities = ["read"]
}
```

```hcl
path "ncdp/data/devices/7/ssh" {
  capabilities = ["read"]
}
```

Roles `ncdp-buildkite-staging-device-6` and
`ncdp-buildkite-staging-device-7` retain the accepted staging workload
contract: JWT role type; audience `urn:ncdp:openbao:staging`; immutable pipeline
subject and exact `cml-staging` step binding; accepted pipeline, build, commit,
branch, step, and job mappings; `sub` user claim; no default policy; one matching
device policy; TTL, maximum TTL, and explicit maximum TTL of 300 seconds; and
one token use.

## Administrative capability proof

The corrected proof created one 60-second, one-use, no-default-policy token per
policy. The trusted administrative token called `POST /v1/sys/capabilities`
with the bounded token and four exact paths. No secret GET occurred.

| Policy | device 1 | device 2 | device 6 | device 7 |
| --- | --- | --- | --- | --- |
| `ncdp-buildkite-staging-device-6-read` | deny | deny | read | deny |
| `ncdp-buildkite-staging-device-7-read` | deny | deny | deny | read |

Each verification-token revocation returned HTTP 204. A subsequent
`lookup-self` with each bearer returned HTTP 403, and final accessor inspection
found zero tokens carrying either staging policy. Standing verification
privilege is zero.

## Legacy staging retirement

Immediately before deletion, the historical policies still granted only their
matching live secret paths, and the historical roles still matched the accepted
pipeline, step, claims, TTL, use, and single-policy definitions. The following
checked sequence completed:

| Order | Object | Delete | Read-back |
| ---: | --- | ---: | ---: |
| 1 | role `ncdp-buildkite-staging-device-1` | HTTP 204 | HTTP 404 |
| 2 | role `ncdp-buildkite-staging-device-2` | HTTP 204 | HTTP 404 |
| 3 | policy `ncdp-buildkite-staging-device-1-read` | HTTP 204 | HTTP 404 |
| 4 | policy `ncdp-buildkite-staging-device-2-read` | HTTP 204 | HTTP 404 |

Standing legacy staging capability to live device secrets is zero. Legitimate
live deployment authority was not retired.

## Live preservation

Live device secrets 1 and 2 remain at KV version 1 with their original creation
timestamps, `2026-08-26T10:53:52.920393177Z` and
`2026-08-26T10:53:53.00344901Z`. Neither was rewritten.

The JWT mount fingerprint remained
`sha256:cfc3f4bc26d00e210450087a863a2051346da039bad2ae852be1187a475a4c75`;
the backend fingerprint remained
`sha256:395c5897493f24c57559874d9428fc4384e03aa5a394aadc88de86ce56aa7a10`.
The existing `ncdp-buildkite-deploy`,
`ncdp-buildkite-cml-deploy-device-1`, and its device-1 policy matched their
before-state fingerprints. The previously absent device-2 live deployment role
and policy remain absent; B2 did not create them.

## Transitional consumer and migration guard

The checked-in staging consumer still selects historical NetBox devices 1/2
and their old role names. Because those roles and policies are now absent, that
legacy path is intentionally fail-closed. B2 did not run `cml-staging`, migrate
Terraform, or claim that runtime consumption of devices 6/7 is complete.

Before the first B3 source or Terraform commit is pushed, a separately reviewed
Buildkite migration execution guard or freeze must prevent the legacy
`cml-staging` step from running during the half-migrated B3/B4 window. No B3
source change is authorized before that guard exists.

Aside from the bounded OpenBao staging-authority mutations documented above,
this increment made zero NetBox, CML, Terraform, Buildkite-configuration,
live-network device/session/configuration, persistent-service, Oxidized,
AuditStore, or observability mutation. B3/B4 and 11B did not start, and 11A
remains paused for ADR 0023 migration.
