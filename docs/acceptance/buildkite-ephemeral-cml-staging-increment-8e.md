# Increment 8E-3 Buildkite ephemeral CML staging acceptance

## Static boundary

Increment 8E-3 started from merged `main`
`637da951857a6fe68f8b4af14fb4ff1d320183e0`. It adds serialized staging after
quality and pipeline-contract and before main-only promotion, preserving human
approval and deploy-gate semantics. It invokes the accepted 8E-2 lifecycle and
keeps network-intent validation read-only.

External acceptance passed on the hardened implementation at runtime commit
`f9d4593bff4a7966d1a4fd44feac601f5aca55c4`. The operator accepted Build #112
as the final live acceptance for that exact runtime commit. This subsequent
evidence-only documentation update changes no executable code, Terraform,
pipeline configuration, identity logic, provider logic, or agent behavior and
does not start another implementation or live-acceptance cycle.

Static implementation and prerequisite setup passed before that build. The
`ncdp-staging` queue exists with concurrency controlled by the pipeline, and its
dedicated agent registered with an external mode-0700 state root and trusted
command hook. The two exact OpenBao staging policies/roles were configured and
read back. NetBox has one dedicated service user, one write-disabled v2 token,
and only the existing view permission for `dcim.device` and `dcim.interface`.
CML 2.10 personal licensing rejected creation of an additional regular user;
acceptance therefore uses the existing personal-controller operator login to
mint a process-memory bearer while rejecting ambient `CML2_TOKEN`. No CML lab,
node, or link was created during prerequisite setup.

Three rejected PR-build diagnostics remained entirely before Terraform creation.
Build #81 exposed reliance on a shell-hook path variable that Buildkite only
documents for polyglot hooks; no evidence or state directory was produced. The
agent-owned command hook now loads its protected credential file from the
documented `$HOME` configuration boundary after admission. Build #82 then
produced sanitized failure evidence for a dedicated NetBox v2 token stored as
only its plaintext component. The unusable token was revoked and replaced with
the complete NetBox v2 bearer presentation; status-only checks for status,
device, and interface endpoints returned HTTP 200. Build #82 had
`creation_outcome=not_attempted`, `destroy_outcome=not_attempted`, no run state,
and zero CML mutations. Neither failed job was retried.

Build #83 verified the corrected Buildkite, NetBox, OpenBao, and CML identity
boundaries, then failed before Terraform initialization because Terraform was
not installed on the dedicated agent path. Its sanitized evidence recorded run
ID `bk-01a03a31-933d-46b0-a55c-18454cb24191`, no lab/node/link realization,
no creation, no cleanup attempt, and no cleanup failure. The run directory held
only an empty Terraform data directory and no state. Terraform 1.15.8 was then
installed at the agent's Homebrew path and the dedicated agent was restarted.
Build #83 was not retried; acceptance proceeds through a distinct build-bound
run identity.

Build #84 crossed the live lifecycle boundary with run ID
`bk-01a03a42-ea65-4a45-b48e-1dce08ceb89d`. It created the exact 13-resource
topology under lab `00f3caf8-2d8b-41c9-b44e-d7168234a768`, reached management
readiness, and then failed closed during core-02 NCDP read-only validation. The
run-scoped known-hosts path had been passed through `ANSIBLE_SSH_COMMON_ARGS`,
but the pinned Ansible libssh connection accepts only `ProxyCommand` from that
option. The adapter now supplies the strict run-scoped trust configuration
through libssh's supported `ANSIBLE_LIBSSH_CONFIG_FILE` boundary.

Build #84 also exposed that Terraform initially created its credential-bearing
state with the agent's permissive process umask before the driver applied its
post-command `0600` correction. The exact live state file was immediately
restricted to `0600`; the Buildkite shell and shared Python entry point now
both set umask `077`, with regression coverage. Despite the primary validation
failure, direct destroy, independent CML absence, empty-state verification, and
state retirement all passed. Build #84 had no cleanup failure and was not
retried.

Build #85 proved direct mode-0600 state creation and passed management readiness
for core-02 and edge-junos-01, but remained rejected. Its NCDP collection failed
closed because the isolated checkout did not contain the ignored pinned Ansible
collections; the driver now invokes the existing exact-pin verifier, and the
dedicated agent uses an external collection path containing `ansible.netcommon
8.6.0` and `cisco.ios 11.4.2`. Direct destroy, independent absence, and state
retirement passed with no cleanup failure.

During Build #85 an operator also opened the core-03 console once and observed
the IOS XE 17.18 initial configuration/security flow caused by the node's empty
configuration. No secret or configuration was entered, but the console operation
independently disqualifies the build from zero-console acceptance. Core-03 now
receives a minimal deterministic, non-credential Day-0 configuration and must
reach CML `BOOTED` in a completely fresh build with zero console access.

Build #86 proved that correction unattended: core-03 reached CML `BOOTED`,
core-02 and edge-junos-01 passed ARP, ICMP, TCP/22, and TCP/830 readiness, and
console operations remained zero. Core-02 collection still failed because the
pinned libssh plugin's host-key policy resolves `~/.ssh/known_hosts` even when
an alternate OpenSSH configuration is provided. Build-scoped trust now uses
`<run>/.ssh/known_hosts`, and only the Ansible subprocess receives the run
directory as `HOME`. Direct destroy, independent absence, and state retirement
again passed with no cleanup failure; Build #86 was not retried.

Build #87 repeated the unattended core-03 `BOOTED` and managed-endpoint
readiness proofs, but the core-02 adapter still returned its generic bounded
collection failure after the run-scoped `HOME` alignment. Cleanup, absence, and
state retirement passed. The adapter now classifies only safe Runner event/task
boundaries so the next fresh build can distinguish unreachable SSH, identity
task failure, and failure before a bounded identity result without retaining or
publishing raw provider output. Build #87 was not retried.

Build #88 classified the core-02 failure as the IOS read-only identity task
failing after authenticated SSH connectivity, rather than an unreachable
connection. Core-03, endpoint readiness, direct destroy, absence, and state
retirement again passed. Because IOS XE can accept SSH before its CLI/facts
subsystem is ready, NCDP read-only provider collection now has a bounded
three-minute retry with a fresh session per attempt. Inventory, policy, and
non-provider failures remain immediate and no write/deploy path is retried.
Build #88 was not retried.

Build #89 reached unattended core-03 `BOOTED` and both managed endpoint
readiness boundaries, then failed before NCDP validation when a one-time
`ssh-keyscan` raced the freshly opened edge-junos SSH service. Direct destroy,
absence, and state retirement passed. Host-key acquisition now retries for a
bounded minute, requires non-empty scanner output, emits only a fixed sanitized
failure, and retains strict run-scoped mode-0600 trust. Build #89 was not
retried.

Build #90 exercised the full three-minute provider-read retry and failed with
the same identity-task classification, proving the condition deterministic.
The external agent collection inventory was then confirmed to include
`ansible.netcommon 8.6.0`, `cisco.ios 11.4.2`, and the required transitive
`ansible.utils 6.1.0`; no collection pin was changed. The adapter now maps only
allowlisted task-result categories and withholds unknown provider text, while
failed-attempt counts are recorded. Cleanup, absence, and retirement passed and
Build #90 was not retried.

Build #91 recorded 13 failed authenticated IOS identity-task attempts across the
bounded window. Its message did not match the first allowlist; no raw text was
published. The classifier now covers additional fixed runtime, transport,
platform, parameter, execution, and response categories. Its final fallback
emits only the intersection with a small approved diagnostic vocabulary plus
the presence of four safe result-shape keys. Cleanup, absence, and state
retirement passed and Build #91 was not retried.

Build #92 narrowed the identity-task result to a generic failed message with an
exception field; the exception content was not published. Classification now
inspects that field in process for fixed Python, Ansible, transport, import,
file, permission, and compatibility categories while exposing only the bounded
category or approved signals. Retry eligibility is now limited to unreachable
connections, SSH session failures, and read-only command timeouts; deterministic
task exceptions fail immediately. Cleanup, absence, and retirement passed and
Build #92 was not retried.

Build #93 confirmed a single deterministic exception but exposed no approved
semantic signal beyond `failed` and `traceback`. The classifier now extracts
only the final bounded exception class identifier ending in `Error` or
`Exception`; it still withholds the exception message, stack, paths, and values.
Cleanup, absence, and state retirement passed and Build #93 was not retried.

Build #94 found no conventional exception class identifier, consistent with an
Ansible traceback fragment that omits its terminal exception line. The fallback
now exposes at most the last four sanitized stack-frame basenames and Python
function identifiers. Full paths, line numbers, messages, arguments, and values
remain withheld. Cleanup, absence, and retirement passed and Build #94 was not
retried.

Build #96 (the clean formatting successor to superseded Build #95) found that
Ansible's exception rendering matched neither conventional traceback frames nor
an `Error`/`Exception` class. The structural parser now also recognizes bounded
identifiers ending in `Fail`/`Failure` and Python basenames followed by function
identifiers under nonstandard traceback rendering. It still exposes no paths,
line numbers, messages, arguments, or values. Cleanup, absence, and retirement
passed and Build #96 was not retried.

Build #97 produced the same result under the broadened structural parser. The
fallback now records only the exception value kind, bounded length/newline
counts, and identifiers beginning with a small trusted set of framework prefixes
such as `Ansible`, `Connection`, `Module`, `Network`, and `Traceback`. Arbitrary
tokens and text remain withheld. Cleanup, absence, and state retirement passed
and Build #97 was not retried.

Build #98 found that the exception value was a 23-character single-line
placeholder with no structural tokens, rather than an actionable traceback.
The remaining child-process boundary was Ansible Runner credential propagation:
the context manager set credentials in the parent environment while Runner also
received an explicit environment mapping. The adapter now places the same two
in-memory credential values explicitly into that child mapping; they remain
inside the temporary Runner boundary and are neither logged nor evidenced.
Cleanup, absence, and retirement passed and Build #98 was not retried.

Build #99 repeated the same identity-task failure after credentials were passed
explicitly through Runner `envvars`, disproving credential propagation as the
root cause. Classifier expansion stopped. One subsequent fresh run writes the
identity task's credential-redacted result to a mode-0600 agent-local diagnostic
outside the checkout and artifact boundary. This temporary diagnostic path is
removed after root-cause isolation and cannot be part of final acceptance.

Build #100 isolated the child-process failure as `AF_UNIX path too long`. The
run-scoped `HOME` used for strict host trust made Ansible's default persistent
connection socket path exceed the macOS Unix-domain socket limit. The adapter
now gives Ansible a short, mode-0700 temporary Runner-local persistent-control
directory while retaining run-scoped strict host trust. This changes no device
credential, network intent, or provider retry classification.

Build #101 confirmed the persistent socket correction and then exposed the
next actual child input failure: libssh rejected core-02 against stale host
trust instead of the freshly established run-scoped file. The adapter now binds
the generated libssh configuration and strict checking directly on the Runner
inventory host as well as in the child environment, avoiding reliance on
ambient plugin discovery while retaining exact-host verification.

Build #102 exercised that direct binding but still observed a changed core-02
host key between acquisition and the first libssh task. Fresh IOS XE can expose
SSH while its first-boot key material is still settling. Host trust acquisition
therefore now requires three consecutive samples with identical public key
material (independent of hashed-host salt) before accepting the run-scoped
strict-trust file.

The next sole-agent run disproved key rotation: stable acquisition passed, but
libssh still rejected a different stored key. Source inspection of the pinned
runtime found the mismatch: `ansible.netcommon` passes a `config_file` argument,
while `ansible-pylibssh 1.4.0` does not map that argument to a libssh option and
therefore continues using ambient known-hosts state. Cisco `network_cli` now
uses the already pinned and supported Paramiko 4.x transport, whose strict
known-host handling reads the explicitly isolated run-scoped `HOME`.

Build #106 passed the complete lifecycle with that transport correction. Before
final acceptance, the temporary Runner diagnostic path was removed, device
credentials were narrowed to Runner's child `envvars` without parent-process
environment mutation, and traceback-shape diagnostics were replaced by a fixed
secret-free fallback while durable operational classifications were retained.
The resulting hardening commit requires its own fresh green staging build.

Build #103 was manually canceled and is excluded from acceptance because two
local processes had registered the same staging-agent name before the build.
The duplicate launchd service was unloaded, and the known-good foreground
runtime was restarted and verified before the next build as the sole connected
agent: PID 62337, name
`ncdp-staging-Net-DevOps.local`, queue `ncdp-staging`. The PID is local
acceptance evidence only; the durable contract remains one registered agent in
the serialized staging queue.

## External PR build

- Buildkite build: #107, passed
- Build ID: `01a03b56-f780-4762-bfee-ea1bae84e576`
- tested commit: `97c9a031d841e472982ace61989f5fe442ee6b09`
- `cml-staging` job ID: `01a03b57-07b0-4777-96f5-018604ff9fc7`
- run ID: `bk-01a03b56-f780-4762-bfee-ea1bae84e576`
- fresh lab ID: `1cc6469e-7c04-4db9-be1c-7dcbc399ca09`
- node IDs: system bridge `da0eb3eb-c6b0-4b59-b863-2a7ed9af26e9`,
  management switch `1da3b400-930c-437c-b0be-c92fb6c6d801`, core-02
  `73980847-00a3-4298-b450-c075bc832089`, edge-junos-01
  `31635f2e-ca38-41db-8b4e-169102de7e19`, core-03
  `85f98eb8-dc9f-426f-bcd2-e01e0e0dd746`
- six fresh link IDs were recorded in the versioned sanitized evidence
- readiness: core-02 76.7 seconds; edge-junos-01 immediately ready when polled;
  ARP, ICMP, TCP/22, and TCP/830 all passed
- core-03 unattended CML state: `BOOTED`
- NCDP read-only validation: core-02 and edge-junos-01 passed on attempt one
- direct destroy from `STARTED`: passed
- independent CML absence and empty-state retirement: passed
- sanitized artifact: `staging-evidence/staging-run.json`
- artifact SHA-256:
  `5bcd7c71f3542cda25702bb13e6e990c7d199047957c6cb30463b3e46a43c235`
- final CML staging count for the run: zero
- console operations: zero
- device writes and NCDP deploy operations: zero

The PR remains unmerged. A later merged-main build is a separate check that the
same staging gate precedes promotion for the merged commit.

## Final accepted runtime build

Build #112 is the final Increment 8E-3 PR live acceptance. It exercised exact
runtime commit `f9d4593bff4a7966d1a4fd44feac601f5aca55c4` after local CML
connectivity was restored, using the sole registered staging-agent process,
PID 62654. Build #109 was not retried.

- Buildkite build: #112, passed in 5 minutes 9 seconds
- Build ID: `01a03c1b-0392-45dc-bba6-c3186bd30f01`
- `cml-staging` job ID: `01a03c1b-19ae-42c5-9cfd-5a17d574fde2`
- run ID: `bk-01a03c1b-0392-45dc-bba6-c3186bd30f01`
- fresh lab ID: `e03c7204-6ffd-4f95-a07f-ce28d0e9defa`
- node IDs: system bridge `a045513a-5bca-49a1-bd35-f3fb5fc605e7`,
  management switch `c2b6c665-eaec-41c6-9dff-9c1387aa741b`, core-02
  `44d1e458-3a99-4a1d-96cb-1116073ea2f1`, edge-junos-01
  `8dc297e2-f176-4283-91b1-2d0643f133a0`, and core-03
  `21b04dee-2b8d-41f8-ae8c-ed9334057346`
- fresh topology creation: all 13 resources passed
- readiness: core-02 passed after 67.6 seconds; edge-junos-01 passed when first
  polled; ARP, ICMP, TCP/22, and TCP/830 passed for both managed endpoints
- core-03 unattended CML state: `BOOTED`
- NCDP read-only validation: core-02 and edge-junos-01 passed on attempt one
- console operations: zero
- device writes: zero; NCDP deploy was not run
- direct destroy from `STARTED`: passed
- independent CML absence: passed
- run-scoped Terraform state retirement: passed
- primary failure and cleanup failure: none
- sanitized evidence schema: version 2
- evidence SHA-256:
  `594ad7144989bd31c52d16e13cf88bf77ca0c74e7988a05ce254664783da3e7f`

This is the accepted PR runtime boundary. The documentation-only closeout
commit records that evidence without changing the implementation exercised by
Build #112.
