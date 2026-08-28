# Protected staging root authority — Phase B3-2B2B0-R

## Authority and scope

This repository-only correction starts from merged main
`aa43b5d20d57995aa0cf8b2120b214282455f92e` and natural merged-main
Buildkite build 198 (`PASSED`). B3-2B2A proved that checkout-controlled
validation, staging, and deployment all execute as UID 501, so external
installation remains blocked pending the reviewed OS remediation. The staging
LaunchAgent remained disabled and unloaded, `cml-staging` remained exactly
`if: "false"`, and protected delivery retained its independent explicit-false
guard.

No OS principal, permission, token, launchd object, protected installation, or
external service was changed by this increment.

## Schema 4 ownership authority

Manifest schema 4 replaces the temporary schema-3 assumption that protected
ownership equals the controller's effective UID. It binds a non-root service
UID/GID, immutable owner UID 0, and an empty supplementary-group set. Startup
requires the exact service UID/GID, rejects root and UID 501, and rejects any
supplementary group. The service UID and primary GID must be the same dedicated
number; `staff`, `admin`, `_developer`, and other shared groups are not valid
service authority.

Immutable policy, credentials, source, runtime, artifacts, tools, and Ansible
content are root-owned and service-group-readable but never service-writable.
Ordinary immutable files are `0440`, directories are `0550` or root-maintained
`0750`, and protected executables are `0550`. Registration tokens remain
root-only `0400` bootstrap authority and are not controller-readable. Only
build workspaces, state, saved plans, recovery metadata, known-hosts, and
bounded logs are service-owned private data (`0700` directories and `0600`
files).

The top-level `/private/var/db/ncdp-staging` service root remains
`root:ncdpstaging 0750`; it is never service-owned. Admission proves the entire
controlling chain through `/private/var/db`. Only the exact `builds`, `state`,
and `logs` children may be service-owned `0700`, preventing the service from
replacing its own `authority/` directory entry.

The controller configuration is fixed at
`/private/var/db/ncdp-staging/authority/config/protected-controller.json`.
Neither `HOME`, environment nor CLI input can redirect it. Admission applies
explicit immutable-root, system-root, and service-mutable policies, including
owner, group, exact mode, symlink, controlled ancestry and digest checks.

## Installation and supply-chain contract

The standing installer now requires explicit service identity and exact
protected Python authority. It invokes `uv venv --python <exact-path>` rather
than ambient Python discovery. A standing installation requires root operator
authority, finalizes immutable source/runtime/artifact ownership before runtime
inventory, then writes root-owned inventories and the final manifest. Temporary
non-root construction remains a test-only simulation.

The reviewed installation authority supplies the exact protected uv executable,
root-controlled uv cache, protected libssh root, and system SDK identity. The
installer derives `SDKROOT`, `CPATH`, `LIBRARY_PATH`, `LDFLAGS`, `CPPFLAGS`, and
`PKG_CONFIG_PATH` internally and does not inherit ambient native-build flags.
It revalidates tools, Python, SDK, native trees/files, and the Ansible tree
before constructing the runtime; the final manifest records verified facts
rather than unchecked operator assertions.

Schema 4 additionally binds exact paths, versions and SHA-256 digests for uv,
Buildkite Agent, Terraform, OpenSSL, `ssh-keyscan`, and `ssh-keygen`; the exact
Ansible collection root, versions and inventory digest; and explicit protected
libssh/OpenSSL native roots. B3-2B2B1 must acquire libssh independently rather
than link against UID-501-controlled Homebrew.

Before final runtime inventory, every Mach-O object must be inspected with
system-protected tooling. Dependencies beneath `/Users/netdevops`, the checkout,
`/opt/homebrew`, temporary build roots, or another validation-writable location
are rejected. Only Apple system libraries or exact digest-bound files in
root-owned protected native roots are accepted.

Controller startup repeats this admission before privileged integration: it
recursively validates each native root and version record, rehashes every
admitted dylib, freshly inspects runtime Mach-O linkage, and requires the exact
native-admission digest. It also recursively revalidates the Ansible tree's
ownership, modes, symlink absence, inventory digest, and the exact collection
metadata versions `ansible.netcommon 8.6.0`, `ansible.utils 6.1.0`, and
`cisco.ios 11.4.2`.

## Buildkite remediation and B4 gates

Every UID-501-readable registration token whose cluster can register into the
staging queue must be revoked. If validation, staging, and deployment share the
cluster, all three replacements use a fixed root-owned
role-to-token-to-UID-to-queue bootstrap and `--token fd://<fd>`; no long-lived
token enters job-readable argv, environment, configuration or files.

Registration requires administratively pausing the exact staging queue,
proving `dispatch_paused=true` and no running/dispatched job, connecting only
long enough to record identity and prove FD isolation, then stopping the agent
while the queue remains paused. Agent-ID stability is measured across a safe
reconnect. OpenBao agent binding remains deferred until that evidence selects
an exact stable claim contract.

Before B4 unfreeze, the agent must disable local hooks, plugins, command
evaluation and unreviewed submodules; enforce allowlisted environment,
repository, pipeline, step, queue, retry and command identity; and use a
root-owned pre-bootstrap/command-hook boundary which invokes only the installed
controller. Cryptographic staging-evidence attestation remains a separate hard
gate. Validation/deployment shared-UID debt must also be resolved before
protected delivery is unfrozen.

## Negative proof

This correction performed zero user/group, permission/ACL, Buildkite token or
queue, launchd, protected-installation, NetBox, OpenBao, CML, Terraform-live,
device/session/configuration, staging-execution, protected-delivery, or pipeline
unfreeze mutation. B3-2B2B1 and B4 did not start.
