# Profiled disposable CML staging

Status: the lifecycle introduced in PR #134 and refined in #136 now consumes
explicit typed staging scope and topology inputs; current evidence is schema v3.
Historical schema-v2 evidence retains its exact reader and meaning.
The user-supplied [main-delivery acceptance](../acceptance/profiled-main-delivery.md)
records the successful chain requiring real CML success. Runtime-relevant
PR/development staging runs through the same lifecycle under the restored [ledger
boundary](../roadmap.md#temporary-development-workflow-exceptions);
canonical non-PR main retains staging and its same-build success digest.

## Purpose and authority

Disposable staging is the real-platform, credentialed, strict-trust, read-only
integration counterpart to modeled service assurance in Batfish. It is not protected
delivery, a deployment authority, a schema-v1 restoration, a B5 acceptance
path, or candidate configuration application. The sole current configuration
write surface remains `ncdp profiled-deploy`, also invoked by authorized main delivery,
for its admitted operation.

Its scope is selected only after full managed resolution through
`NetBoxProfileInventoryProvider` and
`ncdp-profiled-inventory`: core-02 (CAT8000V IOS-XE), edge-junos-01 (vJunos),
transit-ios-01 (IOSv), and access-sw-01 (IOSvL2). The profile catalog projects
node definitions, images, device-side ports, readiness services, and CML
resource policy. The reviewed optimization candidate binds only disposable
`core-02` to the qualified IOL XE realization while LIVE remains CAT8000V;
this is a realization adaptation under benchmark review, not an accepted
replacement. No `ncdp-managed`, `InventoryDevice`, legacy inventory
provider, multivendor adapter, planning function, or write adapter participates.

## Disposable realization

The admitted scope of N devices and explicit topology of L data links creates
`NCDP Staging <run-id>` with N+2 nodes, N+L+1 links and 2N+L+5 managed resources.
The unchanged current proof graph (N=4, L=4) has six nodes, nine links and
17 Terraform-managed resources: a CML lab, system bridge, unmanaged management
switch, four profiled device nodes, nine links, and one lifecycle resource.
Day-0 is management-only and derives each STAGING endpoint from NetBox. It sets
host identity and profile-appropriate management access, including Junos
NETCONF. IOSv explicitly disables network service autoconfiguration, cancels
DHCP interface addressing, and clears any inherited management address before
applying the exact static STAGING binding. Day-0 deliberately excludes underlay,
OSPF, VLAN/trunk, ACL, SNMP, and
interface-description intent. The historical 10.6.12.0/30 bootstrap is absent.

Controlled real-platform diagnosis established one IOSv-specific first-boot
behavior: CML correctly persists the exact static STAGING binding into IOSv
startup configuration, while legacy AutoInstall/DHCP can still retain the
running management interface on a DHCP lease during that first boot. A second
boot from the persisted startup configuration consistently restores the exact
static STAGING binding. The lifecycle therefore gives the first IOSv boot a
bounded 60-second persistence interval and then recycles only the independently
admitted IOSv CML subjects selected by `CmlBootPolicy.IOSV_PERSISTENCE_RECYCLE`.
The current subject is `transit-ios-01`; multiple IOSv instances receive the same
policy independently in canonical scope order. CAT8000V, vJunos, and IOSvL2 are not
recycled. The existing CML reader remains GET-only; a separate run-scoped
recycle boundary admits the exact lab UUID, selected node UUID, logical identity,
IOSv realization profile, and current CML state before issuing exactly one STOP
and one START request. Uncertain mutation transport is independently reconciled
and is never blindly replayed. This is CML realization lifecycle authority, not
network-device configuration-write authority.

The first PR #136 experiment failed safely during Terraform START, before any
transit recycle. User-supplied evidence records create 5.7s, start 3.7s, cleanup
5.4s, total 23.3s, with successful destroy, absence, and retirement and no cleanup
failure. It is not retried. The pinned CML2 provider `0.9.3-beta1`
[startup implementation](https://github.com/CiscoDevNet/terraform-provider-cml2/blob/v0.9.3-beta1/internal/provider/resource/lifecycle/utilities.go)
calls lab START without convergence when unstaged and `wait=false`; its
[update implementation](https://github.com/CiscoDevNet/terraform-provider-cml2/blob/v0.9.3-beta1/internal/provider/resource/lifecycle/update.go)
then starts links using the pre-START snapshot while the lab is transitioning.
That lifecycle update is unsuitable for this linked topology and is no longer
in the active runtime path. Terraform's lifecycle configuration is restored to
PR #135's `wait=true` and reviewed infrastructure/device stages. It remains one
of the exact 17 owned resources, but only Terraform CREATE and saved delete-only
DESTROY plans are used by the active lifecycle.

`ProfiledStagingCmlLabStarter` is a separate, one-shot non-blocking lab mutation
boundary with the same TLS/process-memory bearer model as the recycler. It
re-admits the exact run, lab UUID/title, scope-derived node/link membership,
node IDs/definitions/images, declared identities and profile bindings. The lab
and every scoped/infrastructure node must be `DEFINED_ON_CORE` before first START.
It follows pinned [gocmlclient v0.2.5 Lab.Start](https://github.com/rschmied/gocmlclient/blob/v0.2.5/internal/services/lab.go):
one `PUT /api/v0/labs/<id>/start`; only a definitive 404 permits the legacy
`/api/v0/labs/<id>/state/start` form. Transport failure, 408, or 5xx permits only
one bounded GET readback of the same lab and membership/profile/state bindings.
At least the lab or one node must show an admitted starting/started state, with
no stopped/unknown node states; otherwise the outcome is ambiguous. There is no
mutation retry, initial per-node START loop, or link START. Reader stays GET-only.

The full graph and management-only Day-0 are independently admitted before this
boundary. CML starts the graph together; no device collection occurs until real
SSH/NETCONF readiness and strict trust. Direct-started runtime state is expected
drift from Terraform's stored defined lifecycle. It grants no state surgery or
additional Terraform update: cleanup refreshes the exact owned resource set and
accepts only its matching saved delete-only plan. Any update/replacement in that
plan fails closed and retains state.

After that one admitted CML LAB START, bounded GET observations admit the exact
transit run/lab/node/profile on every sample until its first `BOOTED` (maximum
300 seconds, two-second polling). The existing 60-second interval begins at
that observation, without waiting for CAT8000V, vJunos, or IOSvL2. Identity and
`BOOTED` are rechecked before STOP. `STARTED` alone is not evidence that IOSv
has consumed and persisted Day-0, so neither an earlier interval nor a shorter
one is admitted by the retained diagnosis. After the single STOP/START and
second `BOOTED`, the unchanged realization-scope SSH/NETCONF readiness path follows.
No third boot or mutation replay exists. The user reported the optimized
successful lifecycle at approximately 8m22s (roughly 8–9 minutes); this is a
historical measured result, not a guaranteed duration. Raw timing/job identity
is not recorded in the current acceptance source. No further optimization is
required by this documentation capability.

Before Terraform can create anything, authenticated GET-only CML admission
rejects any existing lab whose title starts with `NCDP Staging` and any active
fixed STAGING management endpoint. After creation, Terraform outputs are only
claims: independent CML GET observations must prove the exact lab UUID/title,
six node UUIDs and profile definitions/images, nine link UUIDs and device-side
slots, and the bounded management-only stored Day-0. The resulting topology
evidence digest binds those observed run-specific UUIDs and relationships.

The run first creates a realization-scope PREPARING `StagingRealizationContext`, then
establishes trust and validates a new READY context. A READY context is invalid
if any trust reference is absent. Validation uses only its staging read-only
targets and `ProfileReadOnlyAdapter`. Readiness is profile-derived: SSH/22 for
CAT8000V, IOSv, and IOSvL2; NETCONF/830 for vJunos. Each readiness reference
binds the run, lab/node UUID, stable identity, endpoint, service, result, and
actual bounded elapsed duration. Unresolved node state is sampled through
bounded GET-only CML observation every 10 seconds. The normal readiness deadline
is 180 seconds and the absolute maximum is 300 seconds. Extension authority is
derived per unresolved device: explicit transitional boot/start state admits
more time, while a first observed `BOOTED` state can admit at most 60 seconds of
post-BOOT service-settle time beyond the normal deadline. The post-BOOT grace
never shortens the 180-second normal window. Unknown state does not grant an
extension, continuously `BOOTED` service failure stops when its grace expires,
and no grace can cross the 300-second maximum. Evidence retains the last bounded
CML state and first observed `BOOTED` elapsed time so a timeout distinguishes
never-booted from post-boot service failure. Read-only collection rechecks the
exact hostname, management interface and STAGING address; IOSv and IOSvL2 also
require their normalized Gi0/0..Gi0/3 physical realization.

A separately authorized diagnostic observer is outside the normal staging
lifecycle and cannot confer acceptance. It discovers the transit node as soon
as the lab exists, begins bounded console attachment attempts while CML state is
`STARTED`, keeps the one available session open to observe boot without sending
configuration, waits for an EXEC prompt, and then issues only reviewed read-only
commands. It remains available until lifecycle completion or the absolute
300-second readiness boundary, but must never delay, suspend, kill, or otherwise
interfere with lifecycle cleanup.

## Credentials and trust

The Buildkite execution boundary uses `BuildkiteStagingSecretProvider`:
one device-scoped OpenBao JWT login/read for each of stable device IDs 1, 2, 8,
and 9. Broad ambient AppRole, NetBox, CML, or device credentials are rejected.
Terraform bootstrap inputs are sensitive; Cisco Day-0 uses an IOS verifier and
Junos uses an encrypted password representation.

Each run creates a private, create-only staging trust root. Its realization-scope host
trust records bind the run, lab UUID, CML node UUID, stable identity, logical
name, automation/CML profile, STAGING endpoint, and profile service. Ambient
known-hosts, auto-add, fallback trust, and relaxed algorithms are prohibited.
Server keys come from three bounded direct Paramiko handshakes per endpoint;
algorithm and fingerprint must be stable across all samples and belong to the
closed host-key algorithm contract. The trust records consume the independently
observed CML anchors rather than self-asserted Terraform identifiers. NETCONF
entries use the exact `[host]:830` known-hosts form.

## Failure, evidence, and recovery

The one-shot lifecycle is admit → fenced create → admitted CML LAB START → exact
profile-required CML recycle → readiness/trust/read-only validate → fenced saved
destroy plan → independent absence proof → state retirement. Cleanup authority
derives from a nonempty known Terraform state,
not from a returned READY context, so partial apply, start, readiness, CML
admission, trust, context, and read-only failures remain cleanup-eligible. A
normal successful realization requires the exact derived address set and its
matching deletes (17 for the current proof graph). Failed partial creation permits only a nonempty subset of those same
addresses and an exactly matching delete-only plan; unknown or empty state is
never destructive authority.

Before create, the run stores one owner-only mode-0600
`recovery-inputs.tfvars.json` containing the exact admitted Terraform inputs.
It contains derived password verifiers, never plaintext passwords or OpenBao
session material. Normal operations and guarded recovery use those same bytes.
Recovery therefore needs no OpenBao access; it validates directory ownership,
input/state/lab binding, the known resource subset, and a saved exact-delete
plan. It cannot create or start, and state, backup, plans, and recovery inputs
are retired only after independent CML absence is proven.

Schema-v3 `ProfiledStagingEvidence` binds the typed scope and preserves source commit, observed lab and
run-specific topology, final READY context digest, actual trust generation,
per-device readiness and read-only facts, per-subject profile-required recycle
attempts/references, create/start/
destroy/absence/state retirement, and separate primary/cleanup failures. An
uncertain Terraform, lab-start, or profile-required recycle mutation is never replayed: known owned
state may proceed only to bounded
cleanup, while unprovable ownership is `AMBIGUOUS` and retained for review.

Optional `lab_start_evidence` binds `staging-lab-start:<run-id>` to the observed
lab, nodes, topology digest and acknowledged/reconciled start facts. It is
present only after start success. Historical schema-v2 success without this
reference remains parseable; new Buildkite success additionally requires it.

Optional `timings_seconds` adds only closed phase names and finite nonnegative
monotonic durations to current evidence, including failed phase durations. The phases
are Terraform create (including its saved plan), admitted CML LAB START, profile-required first
boot observation, persistence interval, STOP completion, second boot,
SSH/NETCONF readiness, read-only validation, cleanup, and
whole lifecycle total. Total includes admission, setup, trust, and nested phases; do
not sum it with those phases. The Buildkite sanitized summary displays these
numbers; no provider text or secret is a timing payload. Compare total and
per-phase durations with the former approximately 11-minute job, allowing for
wrapper setup/publication time outside the lifecycle total. Existing evidence
without timings remains valid through `ProfiledStagingEvidenceV2`. Its
transit-specific fields are never reinterpreted as multi-instance evidence.
`read_profiled_staging_evidence()` dispatches exact versions; new Buildkite
success requires schema v3 and every profile-required recycle subject.

Terraform uses `for_each` over the Python-admitted device and data-link maps.
Management switch slots and presentation coordinates derive from canonical
scope order; device slots derive from the reviewed realization profile and
NetBox management binding. The unchanged topology digest is
`sha256:764405fa9a44d7c42ae402ec2fa1d03c2b7dd9ba0916954e03c7a7d5baf68064`.
Historical Terraform resource addresses remain historical; old retained runs
must be reconciled with their matching reviewed version, never fed to the new
cleanup address contract. No runtime state migration is part of this change.

## Buildkite activation

`LocalTerraformOperations` accepts injected inventory and secret providers;
local defaults remain `NetBoxProfileInventoryProvider` and
`OpenBaoSecretProvider`. The Buildkite driver explicitly supplies the profiled
NetBox provider with the dedicated staging token and the existing
`BuildkiteStagingSecretProvider` with one OIDC JWT and validated context. Both
entry points call the same `ProfiledStagingLifecycle` exactly once. CML reader
and recycler accept the process-memory bearer directly; only bounded Terraform
subprocesses receive it as `CML2_TOKEN`. Their mutation and GET-only contracts
are unchanged.

Runtime-relevant PR/development and canonical non-PR main builds run validation
→ Batfish → CML without branch filtering. Non-runtime changes remain excluded by
the shared path boundary.
Repository commands soft-fail for continuation; staging retains its
real nonzero exit and truthful evidence, but no longer guarantees aggregate
Buildkite failure or merge blocking. Verified staging success publishes a
same-build evidence hash required by the separate schema-v2 main promotion.
Failure publishes no success authority. The staging lifecycle itself gains no
device-write authority. See the current
[operations runbook](buildkite-ephemeral-cml-staging-operations.md) for the
external trusted-agent prerequisite, evidence, and retained-state handling.

The present implementation enforces the named proof population and fixed graph
counts. These are current scope limitations, not a permanent architectural
cardinality. CAP-POPULATION-SCOPES owns generalization while preserving exact
membership, topology, resource ownership and cleanup checks. Serialized
identities such as `profiled-four-device` remain unchanged.
