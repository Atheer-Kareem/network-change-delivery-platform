# Profiled configuration chronology acceptance

## Acceptance and evidence boundary

**CAP-CONFIG-CHRONOLOGY — ACCEPTED.** The user explicitly accepted the merged
implementation and controlled independent observation after reviewing the
runtime evidence below. The [capability ledger](../roadmap.md#cap-config-chronology--independent-prewritepost-chronology)
is authoritative for state; the [current chronology contract](../architecture/audit-and-configuration-history.md#current-profiled-configuration-chronology)
defines behavior.

The real independent Oxidized observation plane is runtime-verified against
core-02, including current service, readiness, trust, private history and
metadata-only collection.

Current PRE/write/POST coordinator ordering, failure precedence, parent/child
durability, receipt binding and no-replay behavior are comprehensively
offline-validated in merged PR #147.

Full integrated EXECUTION chronology will receive supplemental runtime evidence
on the next legitimate network write. No device change is required or should be
manufactured solely for acceptance. **Supplemental EXECUTION runtime evidence is
not a pending acceptance condition.**

This record preserves the controlled local runtime verification and user
sign-off supplied in the acceptance session. The standalone observation was not
an integrated deployment. No Buildkite build was triggered, continued or used to
manufacture evidence; the waiting build remained untouched. No runtime operation
was repeated for this documentation closeout.

## Accepted implementation

Merged [PR #147](https://github.com/Atheer-Kareem/network-change-delivery-platform/pull/147),
main commit `77b5a768ba259e99e02866d525819bf73b05f4d0`, established:

- Required successful independent PRE before device execution; PRE failure
  invokes zero device commands and all paths permit at most one invocation.
- POST immediately after the command boundary, including non-success and
  uncertain command-start cases. Device failure retains precedence; evidence
  failures never replay the command.
- Exact PRE-after / POST-before revision-chain validation. Intervening
  independent history becomes AMBIGUOUS, never silently rebased.
- Durable parent independence from chronology-child success; child publication
  only after durable-parent readback, with deterministic current child identity.
- Same-build chronology receipt and final-evidence receipt validation without
  AuditStore authority. The durable child remains the correlation authority.
- `TEMPORALLY_BRACKETED` with `causality = NOT_PROVEN`.
- COMPLIANCE performs no chronology activity. The viewer preserves a valid
  durable parent when chronology is unavailable or invalid.
- Current plane pinned to repository `oxidized:ncdp-lab-actual-state` and group
  `managed`; historical chronology schemas, bytes and routes remain unchanged.

Final implementation validation: full local pytest **2,382 passed, 5 skipped**;
focused chronology regressions **428 passed**; Docker quality **2,340 passed,
47 skipped**. Relevant Ruff, format, diff, package, Ansible and static checks
passed. These are implementation validation results, not newly rerun runtime
gates for this closeout.

## Runtime and operational reconciliation

Acceptance used clean branch `main` at
`77b5a768ba259e99e02866d525819bf73b05f4d0`, equal to pulled `origin/main`.
The reviewed container definition, loopback API `http://127.0.0.1:8888`, host
trust and private Git history verified. Readiness schema 3 validated its private
path, freshness, container identity, host-trust hash and absent ambiguity guard.
The managed nodes were `netbox-device-1`, `netbox-device-2`, `netbox-device-8`
and `netbox-device-9`.

Initial inspection found the installed immutable reconciler at
`d6b4ef11620f8aeb0e976c38e9008ce40e30971e` still carrying the retired inventory
provider and two-node contract. The readiness marker was absent; bounded logs
recorded reconciliation failure. The already-reviewed
[`scripts/oxidized/update_service_runtime.sh`](../../scripts/oxidized/update_service_runtime.sh)
installed merged main. Installed module bytes were verified against that source.
One controlled reconciliation then returned `READY`; the existing verified
container remained running.

Existing launchd ownership, private paths and authority model were preserved.
Routine ephemeral Oxidized source SecretID issuance occurred as designed.
Persistent credential rotation/reissuance did **not** occur. No OpenBao role or
policy changed, and no credential values were printed. This was an operational
installation correction, not a new capability or credential architecture.

## One real independent observation

The supported metadata-only observation path collected `netbox-device-1 / core-02`
once against an existing private-history baseline.

| Field | Verified value |
|---|---|
| Result | `CHANGED` |
| Request UUID | `87c3246d-3030-40ba-968c-d4a2e627d877` |
| Requested | `2026-09-08T07:55:32.764817+00:00` |
| Completed | `2026-09-08T07:55:38+00:00` |
| Settled | `2026-09-08T07:55:38.986805+00:00` |
| Before commit | `631a0542c74b95af5a161397e211138d07ef89ad` |
| Before blob | `51fac418c37409e3e29c14517fd778a034ff182d` |
| After commit | `459af45f33dcfd3264cc7ca7c4d62bade0a6e728` |
| After blob | `208dd849addffd4d36b181b6af4785fcd7e5f200` |
| Canonical path | `managed/netbox-device-1` |

Typed metadata, object IDs, UTC ordering and revision advancement validated.
**CHANGED means the independent Oxidized history advanced during collection.
It does not establish NCDP causality.** Raw configuration was not read/reported
by NCDP acceptance tooling; Oxidized alone performed the authorized configuration
collection. **Device configuration writes = ZERO.**

## AuditStore and viewer compatibility

Read-only typed API verification established:

| Record family | Before → after |
|---|---|
| Historical durable records | `11 → 11` |
| Current profiled records | `1 → 1` |
| Current chronology children | `0 → 0` |

Store filesystem entry metadata remained unchanged. The standalone observation
intentionally fabricated no deployment parent, chronology child or chronology
receipt: no legitimate EXECUTION parent existed for this observation.

Build-420 durable record `01a07d93-9eb1-4385-804c-c28bf81376d7` remained valid as
COMPLIANCE / COMPLIANT with no chronology child. Its existing
[durable-publication acceptance](profiled-durable-publication.md) remains
historical evidence and requires no migration.

The loopback viewer returned HTTP 200 with correct current durable parent facts
and `Configuration chronology: NOT REQUIRED — COMPLIANT`. CSP, no-store and
privacy checks passed: no credential reference, raw configuration, filesystem
locator or environment values were exposed. The temporary viewer was stopped.

The temporary PR/development CML exception remains ACTIVE. No population,
promotion target, write admission or other capability state changes accompany
this acceptance closeout.
