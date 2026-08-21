# Cisco interface-description vertical

## Status and supported operation

Increment 2 is complete. Real CML execution, independent post-validation, and
read-only idempotency evidence are recorded in the
[live acceptance report](../acceptance/cisco-interface-description-increment-2.md).
The successful validation path did not make targeted recovery eligible, so no
live recovery write was attempted; recovery policy and outcomes remain covered
by automated tests. The only supported operation is setting one non-empty
description, up to 240 characters, on one explicitly selected, non-protected
Cisco IOS/IOS XE interface. Arbitrary commands, fleets, other configuration
properties, vendors, and production targets are out of scope.

## Temporary boundaries

`LocalYamlInventoryProvider` resolves one logical target from an untracked local
YAML file. Inventory contains connection coordinates, expected hostname,
platform, and protected-interface policy, but no credentials. This boundary is
intended to be replaced by NetBox without changing lifecycle policy.

`EnvironmentSecretProvider` reads only `NCDP_DEVICE_USERNAME` and
`NCDP_DEVICE_PASSWORD`. Values are never accepted as CLI arguments or placed in
inventory, plans, evidence, logs, exceptions, or retained Runner artifacts. This
boundary is intended to be replaced by OpenBao.

## Trusted collection and preflight

Ansible Runner invokes `ansible.netcommon.network_cli` with libssh. Host-key
checking is enabled, auto-add is disabled, and a pre-existing entry is required
in the current user's standard `~/.ssh/known_hosts`. Increment 2 does not support
a custom trust-store path, discover keys with `ssh-keyscan`, or automatically
trust keys. Collection uses `cisco.ios.ios_facts`,
`cisco.ios.ios_interfaces`, and `cisco.ios.ios_l3_interfaces`, then immediately
normalizes only identity, IOS XE version, interface existence, description,
enabled state, and bounded IP-address evidence.

Planning fails closed unless the target resolves exactly once, platform is
`cisco_iosxe`, credentials and trusted authenticated access are available,
observed hostname matches inventory, the interface exists, its description is
unambiguous, and inventory policy does not protect it. `GigabitEthernet1` is
always protected for the personal-lab candidate. Interface operational state
alone never establishes safety.

## Immutable approval and execution

The plan records the exact `cisco.ios.ios_config` parent and lines used for the
write and targeted recovery. Deterministic compact, sorted-key UTF-8 JSON—without
the digest field—is hashed with SHA-256. The CLI preview renders directly from
that same artifact. Deployment requires an exact `--approve-digest` match, then
re-resolves and compares the inventory name, host, port, platform, and expected
hostname before any live collection. Deployment performs fresh identity and
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

The initial typed `ChangeRecord` distinguishes blocking, stale plan, execution
failure, ambiguity, validation failure, successful recovery, and recovery
failure. It includes bounded stage results and provider identity, never raw
Runner events, full configuration, usernames, passwords, or host keys. Evidence
is observational and never authorizes a write.

## Live acceptance procedure

Normal automated tests use provider fakes and require no CML access. Live
acceptance is deliberately separate:

1. Confirm environment credentials, reachability, and existing host trust.
2. Perform read-only identity, interface, description, and bounded L3 discovery.
3. Have an operator select a safe non-management interface from the evidence.
4. Generate and display the exact execution/recovery artifacts and plan digest.
5. Stop until the operator explicitly approves that exact digest.
6. Run deployment once, validate independently, and exercise documented targeted
   recovery acceptance under operator control.

No live configuration write is authorized by repository work or plan creation.
Acceptance evidence must be documented only after the real procedure occurs.
