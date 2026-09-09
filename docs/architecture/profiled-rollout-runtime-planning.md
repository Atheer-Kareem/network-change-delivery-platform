# Protected rollout planning and parent promotion

CAP-PROFILED-ROLLOUT remains **IN PROGRESS**. Increment 3 repository implementation
is complete. Protected external planning authority is **ACTIVATED and VERIFIED**
against reviewed runtime commit `a6dd4762b6ff022c30bd8bb4572571d149080995`.
Increment 4 added reusable [authorization, preflight and local reservations](profiled-rollout-execution-admission.md).
Increment 5 adds the separate [protected execution path](profiled-rollout-execution.md),
subject to post-review hook activation and explicit human continuation. The
planning/promotion contracts and historical checkpoint below remain unchanged.

## Parallel protected planning path

```text
engineering receipts → Batfish success → real CML success
→ profiled-rollout-live-plan → profiled-rollout-promotion → STOP
```

The existing single-target path and `deployments/live/profiled-demo.yaml` remain
unchanged. Rollout artifacts, receipts and promotion use distinct names/types;
single-target deployment cannot consume them. Both new jobs are canonical
non-PR main-only with the shared runtime-change condition and disabled retries.
Rollout planning uses `ncdp-deploy` and concurrency group
`ncdp/profiled-live-delivery`, shared with single-target live planning/deployment.
Promotion uses `ncdp-validation` without credentials. The new jobs do not soft
fail; existing single-target presentation behavior is unchanged.

The reviewed command hook source admits only `profiled-live-plan`,
`profiled-rollout-live-plan` and `profiled-deploy`. It retains exact repository,
main/non-PR/retry/queue/command/commit/clean-checkout/pipeline and private-env
checks. AuditStore is required only by existing single-target deployment, never
by rollout planning. No rollout deploy key is admitted.

## Fixed reviewed intent and observed inventory

The fixed `deployments/live/profiled-rollout.yaml` uses the existing
`ProfiledRolloutSelectionIntent` and three ordered selector clauses. Its loader
rejects links at every component, nonregular/oversize/empty files, duplicate YAML
keys, multiple documents and unknown fields. There is no environment/path
selector, fallback or discovery authority.

GET-only NetBox inspection before this proposal confirmed:

| Clause | Logical target / stable device | Reviewed interface / stable interface |
|---|---|---|
| IOS-XE | core-02 / device 1 | GigabitEthernet2 / interface 2 |
| Junos | edge-junos-01 / device 2 | ge-0/0/1 / interface 4 |
| IOS | transit-ios-01 / device 8 | GigabitEthernet0/1 / interface 14 |
| IOS | access-sw-01 / device 9 | GigabitEthernet0/1 / interface 18 |

Identities use the `netbox:dcim.device:N` / `netbox:dcim.interface:N` namespaces.
Each interface belongs to the exact device and was inventory-nonprotected.
No device configuration was read to choose these inputs. Each clause contains
its exact harmless description; wave size is 1 with automatic existing
family-representative canary derivation. The selected payload is proposed D1;
merging or promoting it does not change device state or advance D0.

## Independent credential boundary

Repository `DEVICE_IDS = (1, 2, 8, 9)` is an explicitly reviewed current-lab set,
not a projection of selectors, population, passive scopes, families or profiles.
Future device 10 (or any other ID) has no permission automatically. The existing
`ncdp-buildkite-profiled-deploy` role and
`ncdp-buildkite-profiled-deploy-read` policy retain exact KV-v2 read-only paths:

```text
ncdp/data/devices/1/ssh
ncdp/data/devices/2/ssh
ncdp/data/devices/8/ssh
ncdp/data/devices/9/ssh
```

No wildcard/list/write/admin capability is added. Persistent SecretID TTL/uses
remain 0/0; issued service tokens remain 300 seconds, one use, no default or
identity policies. Verification checks exact role/policy, installed pair,
non-consuming administrative token lookup, actual exact four provider reads,
and a separate one-use token receiving HTTP 403 for device 999999. Timeout or
another status is not accepted as denial. No mutation is retried.

`ProtectedRolloutCredentialAuthority` emits the role identity, stable device,
exact non-secret reference and `permitted=True` only for this static set. All
member admissions precede any child secret load/collection. Each existing child
planner must still perform its own OpenBao read and truthful observation:

```text
static permission != actual secret availability != population membership
!= operation admission != rollout authorization
```

## Publication and independent promotion

The existing planner resolves the whole population before expansion/admission,
then calls the unchanged schema-v2 child planner sequentially. Default timestamps
remain child-owned after observation; explicit test overrides remain supported.
Any child failure publishes no parent. LIVE trust and all 13 engineering receipts
plus Batfish/CML success digests are required before protected rollout collection.
CML soft-fail presentation cannot substitute for its success receipt.

Parent v1/v2 semantics remain unchanged. Exact embedded child JSON bytes are
retained. The outer create-only JSON has a deterministic final newline and its
own byte hash. `RolloutPlanningPublication` schema v1 under
`profiled-rollout-planning-result` binds build UUID, commit, kind, parent schema,
parent semantic digest and exact published byte digest. Annotation displays
ordered selected identities/interfaces, positive child statuses, observed and
desired descriptions, child digests, canaries, waves and parent digest.

Promotion independently reloads the fixed intent and same-build receipt/artifact,
strictly dispatches parent v1/v2, checks commit/instructions/current Git expansion,
exact protected credential decisions and all child bytes/results, and verifies
all engineering/Batfish/CML prerequisites. It does not query devices or NetBox.

`ProfiledRolloutPromotion` is a distinct **rollout promotion schema v1**, not
single-target `ProfiledPromotion` v2. It binds build/commit/change identity,
parent version/type/semantic and byte digests, ordered child stable identities,
kind/semantic and byte digests, exact cohorts, validation/Batfish/CML digests and
its own digest. Its artifact is create-only; metadata records both
`profiled-rollout-promotion-digest` and
`profiled-rollout-promotion-artifact-digest`. Readback must match an independently
reconstructed promotion. A self-digest alone does not establish authority.

Positive all-COMPLIANT planning publishes one typed compliance parent and no
promotion, human authorization, execution, recovery or chronology. Missing
artifacts never mean compliance. Promotion by itself grants no execution
capability in this increment.

Batfish remains existing B4 network/service assurance, not exact description
candidate assurance. CML remains real same-build realization/readiness/trust and
read-only integration, not candidate-write rehearsal. CAP-OP-ASSURANCE remains
DEFERRED; the temporary PR/development CML exception remains ACTIVE.

## Verified post-review activation

Explicitly authorized activation completed against reviewed runtime commit
`a6dd4762b6ff022c30bd8bb4572571d149080995`, after natural Buildkite #461 passed
for that exact commit. The working tree was clean and PR #162 remained unmerged.
The blocked-tail audit established **15 INERT_COMPLIANT**, **7
INERT_PROMOTION_FAILED**, **0 LIVE_PAUSED_PROMOTION** and **0 UNKNOWN_BLOCKER**.
No new canonical-main builds appeared in the race check. Historical blocks were
not canceled, retried or continued. A positive COMPLIANCE path returns before
consuming promotion/write authority; a failed promotion without its required
digest cannot authorize deployment. A visible block alone is not a live promotion.

The reviewed hook was installed at the existing agent-owned
`~/.config/buildkite/ncdp-lab/hooks/ncdp-deploy/command`. Installed bytes matched
reviewed source; hook and directory retained `netdevops:staff` ownership and
mode **0700**. `profiled.env` and the dedicated persistent pair remained
byte-identical. The source/installed hook SHA-256 was
`d0f23c56581446a14d1accf52a0e63741da31b4e692c1f3094dfedb73ffd11eb`.

`OpenBaoProfiledDeployConfigurator.configure()` ran once. The existing dedicated
policy expanded exactly once from device reads **1/2** to **1/2/8/9**; the existing
role was already exact and required no mutation. Independent readback verified
only those exact KV-v2 read paths, with no wildcard/list/write/admin capability.
The existing persistent SecretID was reused, not issued or rotated; its TTL/uses
remain **0/0**. Tokens retain TTL/max TTL **300 seconds**, one use, the dedicated
policy only, and no default or identity policies. Verification using the existing
pair returned HTTP **200** for each exact device credential read **1/2/8/9** and
HTTP **403** for unrelated device **999999**. No credential values were emitted.

No device configuration access, CML, NetBox, AuditStore or observability mutation
occurred. No manual Buildkite build or merge was performed. This establishes
protected planning credential availability; rollout execution still does not
exist and later-stage runtime acceptance remains pending.

## Increment 3 runtime checkpoint

Natural canonical-main webhook **Build #463** verified Increment 3 on commit
`97fb312cefa66b9716e1dcee33152404e6d3211a`, build UUID
`01a08609-fad7-4c4e-86c6-9d052420e8d8`. Both `profiled-rollout-live-plan` and
`profiled-rollout-promotion` **PASSED**, exit **0**, **not soft-failed**. All 13
engineering validation receipts existed and verified for this same build/commit.

| Binding | Exact digest |
|---|---|
| Batfish success | `sha256:bce02aa833eb99dde60f96ae6f854313defc97ce245516871d3f5e616015219b` |
| Real CML success | `sha256:cf60ab336cb142510b50c04d15d6be7be9c97356367cace65b87310a5e62b341` |
| Parent semantic | `sha256:138527ccb624dcf7949b0912b717e7e0f0faf658ddd0e5ed56172a6cbb56a644` |
| Parent artifact bytes | `sha256:e48492f4f06eb07806da2d68b95fb5d9a64440fd24c0e42b59eb8f5e6479cf9e` |
| Promotion semantic | `sha256:6136317b6e5775550726a6d2afe027caca5e231a2ab5e9f180cac6023014ec31` |
| Promotion artifact bytes | `sha256:450503328a9fd24c673a469eb301e81931f2b229bf4a194a5dbf621d81986596` |

The parent was a **schema-v2 rollout PLAN**, with all four children DEPLOYABLE.
Canaries were stable devices **1, 2**; ordered waves were **[8]**, then **[9]**.
This was planning and promotion only. That exact committed graph/implementation
contained no rollout authorization or execution path, and therefore no rollout
execution artifact, durable execution record or chronology publication path.
External artifact LIST permission was unavailable; this absence was established
from the exact graph/implementation, not independent artifact enumeration.
No capability acceptance is implied by this Increment-3 checkpoint.

## Post-review activation order

The completed activation followed this bounded procedure. Any future application
requires its own explicit approval and verification; these instructions do not
request another activation.

1. Recheck the exact reviewed commit and clean checkout. Inspect canonical main
   builds read-only and classify blocked tails against their own contracts.
   Inert COMPLIANCE/failed-promotion tails do not block activation; a live paused
   promotion or genuinely unknown authority does. Require no active delivery;
   do not unblock, retry or cancel another delivery as an activation shortcut.
2. Install only reviewed
   `scripts/buildkite/profiled_deploy_agent_command_hook.sh` as the existing
   agent-owned `ncdp-deploy` command hook. Verify owner, directory mode 0700,
   hook mode 0700 and byte equality with the reviewed source. Leave `profiled.env`
   and the dedicated external pair file unchanged.
3. Load the **existing** dedicated pair using the installer module's private-file
   reader (`read_credentials`), not `issue` or the general personal AppRole.
   With separately authorized operator context, use
   `OpenBaoProfiledDeployConfigurator.configure()` for only the existing exact
   policy/role, followed by `verify(existing_pair)`. Do not invoke an installation
   path that could issue credentials if state is missing. Missing/invalid
   persistent credentials require separate investigation/approval.
4. Require exact role/policy readback, persistent-pair validation, unchanged
   token contract, four real exact credential reads and unrelated-path denial.
   Report outcomes only; never emit pair/token/device credential values. No
   device configuration read/write is involved in this credential verification.
5. If any policy/role mutation outcome is uncertain, **STOP without retry**.
   Independently GET/reconcile role/policy state before deciding another action.
   Do not rotate SecretIDs as a shortcut. Verify external pair/env bytes unchanged.
6. Only after hook and OpenBao verification succeeds should the user merge.
   The natural canonical main build supplies the first real protected rollout
   planning/promotion evidence. No manual protected build is needed, and no
   rollout execution is available.

Increment 4 supplies reusable authorization, preflight and local reservations.
Protected runtime integration, the actual fieldless rollout block, single-target
overlap composition, JIT child execution, sequential cohorts, stop/partial
outcomes, final whole-population validation, parent durable execution evidence,
chronology and later-stage runtime acceptance remain pending. See the
[roadmap](../roadmap.md#cap-profiled-rollout--bounded-profiled-multi-target-rollout).
