# Cisco interface-description vertical

## Status and supported operation

The current schema-v2 `profiled-plan` / `profiled-deploy` path admits the
explicit `cat8000v_iosxe`, `iosv_159_3_m12` and `iosvl2_2020` operation entries
for one non-empty interface description (up to 240 characters) on an explicitly
selected, non-protected interface. All three reuse the existing Cisco families;
family compatibility alone does not admit writes. The protected Buildkite
credential identity has a separately reviewed exact device-1/2/8/9 scope. Build
#472 runtime-accepted the IOSv/IOSvL2 child lifecycles within the bounded rollout.
See [profile reuse](profile-reuse-write.md) and [rollout
acceptance](../acceptance/profiled-rollout.md).
The [profiled CLI acceptance](../acceptance/profiled-deploy-live-acceptance-pr132.md)
and [current main acceptance](../acceptance/profiled-main-delivery.md) establish
successful independent validation without recovery writes. The original
[Increment 2 record](../acceptance/cisco-interface-description-increment-2.md)
remains historical evidence of the vendor kernel and idempotency.

## Provider boundaries

NetBox is the primary personal-lab source for device identity, endpoint,
platform, eligibility, interface identity, and protection tags. Current profiled
deployment requires the profiled NetBox boundary; legacy YAML
providers remain supporting test/compatibility machinery, not an alternate current LIVE path.

OpenBao is the primary personal-lab credential path. AppRole obtains a
short-lived single-use OpenBao token, then reads the exact static Cisco IOS/IOS-XE
credential selected by stable NetBox device identity. The plan binds only the
non-secret provider source/reference. `EnvironmentSecretProvider` remains an
explicit test/offline option; there is no automatic fallback.

## Trusted collection and preflight

Ansible Runner invokes `ansible.netcommon.network_cli` and explicitly selects
Paramiko with `ansible_network_cli_ssh_type=paramiko`. Host-key checking is
enabled, auto-add is disabled, and a pre-existing entry is required in the
explicit profiled LIVE trust generation. It does not use ambient user trust,
`ssh-keyscan`, auto-add, fallback or algorithm relaxation. Profile-bound
read-only collection normalizes bounded identity/interface evidence using the
Cisco Ansible collector family.

Before deployment preflight can load credentials or collect device state,
`execute_profiled_plan` asks the selected writer adapter to verify its effective
Runner collection path against `ansible.netcommon 8.6.0` and `cisco.ios 11.4.2`.
CAP-RUNTIME-VERIFY is accepted; it checks path/manifests/versions, not installed
file cryptographic integrity. Failure is bounded, with execution/recovery not
attempted. See [operations](buildkite-profiled-delivery-operations.md).

Planning fails closed unless the target resolves exactly once, profile/operation admission is
an explicit reviewed interface-description catalog entry, credentials and trusted
authenticated access are available, observed hostname matches inventory, the
interface exists, its description is unambiguous, and inventory policy does not
protect it. The current CAT8000V management interface is `GigabitEthernet1`;
IOSv/IOSvL2 management is `GigabitEthernet0/0`. Protection comes from resolved
inventory, never interface position or a writer-side device table. Interface
operational state
alone never establishes safety.

## Immutable approval and execution

The plan records the exact `cisco.ios.ios_config` parent and lines used for the
write and targeted recovery. Deterministic compact, sorted-key UTF-8 JSON—without
the digest field—is hashed with SHA-256. The CLI preview renders directly from
that same artifact. Deployment requires an exact `--approve-digest` match, then
re-resolves and compares inventory source, stable device and requested-interface
object identities, name, host, port, platform, and expected hostname before any
live collection. It then compares the current non-secret credential source and
reference before retrieving credentials. Deployment performs fresh identity and
interface collection immediately before writing. Changed,
missing, already-compliant, or otherwise stale preconditions block execution.

The executor applies the stored section once with `match: line` and
`save_when: never`. It does not retry an ambiguous write. After unambiguous
success, an independent fresh collection must observe the exact desired
description; Runner task success is not deployment success.

## Targeted recovery and evidence

If the write is known to have succeeded, post-write collection or identity
failure is final and requires operator investigation without automatic recovery.
Only a successful, identity-matching collection whose description differs is
eligible for the approved inverse description artifact. It restores the exact
previous description or uses `no description` when none existed, then verifies
fresh state. Ambiguous writes are not retried or automatically recovered.
Recovery failure is final and requires operator action. Ambiguous recovery is a
distinct final outcome and is never retried.

The current typed schema-v2 `ProfiledChangeRecord` distinguishes blocking, stale plan, execution
failure, ambiguity, validation failure, successful recovery, and recovery
failure. It includes bounded stage results and provider identity, never raw
Runner events, full configuration, usernames, passwords, or host keys. Evidence
is observational and never authorizes a write.

## Live acceptance procedure

Normal automated tests use provider fakes and require no CML access. Live
acceptance is deliberately separate:

1. Confirm authorized NetBox/OpenBao providers and the explicit profiled LIVE trust.
2. Perform read-only identity, interface, description, and bounded L3 discovery.
3. Have an operator select a safe non-management interface from the evidence.
4. Generate and display the exact execution/recovery artifacts and plan digest.
5. Stop until the operator explicitly approves that exact digest.
6. Run deployment once, validate independently, and exercise documented targeted
   recovery acceptance only if separately authorized and eligible.

No live configuration write is authorized by repository work or plan creation.
Acceptance evidence must be documented only after the real procedure occurs.
