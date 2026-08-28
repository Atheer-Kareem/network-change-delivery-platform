# Protected staging runtime composition — Phase B3-2B1

## Authority and non-executing scope

This repository-only increment starts from merged main
`6861d96ed237d739c5d7e7d42248fa1b2ee827e9` and natural merged-main
Buildkite build 193 (`PASSED`). ADR 0023, the ten-resource managed-pair graph,
and the B2-G execution freeze remain authoritative. The staging LaunchAgent
remained disabled and unloaded, `cml-staging` remained exactly `if: "false"`,
and protected delivery retained its independent explicit-false guard.

No protected bundle or executable runtime was installed. All runtime
construction and integration behavior was exercised with mocks, fakes, and
temporary directories only. B3-2B2 owns exact merged-main external
installation and admission; B4 still owns hook cutover and agent re-enable.

## Executable authority

Manifest schema 3 rejects unknown fields and separately binds the reviewed
`source/` inventory and final generated `runtime/` inventory. The final manifest
is written only after the wheel, hash-frozen production requirements,
non-editable Python 3.12 runtime, and controller entry point exist. It binds
both inventories, their aggregate digests, the wheel and requirements digests,
controller entry-point identity, immutable Buildkite pipeline, NetBox endpoint,
OpenBao endpoint, and CML CA PEM digest authority. A normal run
requires the Buildkite pipeline UUID and commit to equal the installed
manifest. External configuration contains private paths and admitted absolute
tools only; it cannot override endpoints, targets, device IDs, addresses,
OpenBao roles, Terraform source, or state.

The exact NetBox authority is:

- device 6 `stg-core-02`, site 1, device type 1, interface 9
  `GigabitEthernet1`, IPAddress 9 `192.168.4.30/24`, homolog 1;
- device 7 `stg-edge-junos-01`, site 1, device type 2, interface 10 `fxp0`,
  IPAddress 10 `192.168.4.31/24`, homolog 2;
- live homolog 1 remains active Cisco device type 1 at `.14/24` and live
  homolog 2 remains active Junos device type 2 at `.20/24`.

The resolver proves exact device, interface, IPAddress, primary-IP,
assignment, tagless staging, custom-field, platform, device-type, site, role,
status, and unique reverse-homolog identity. Device 3 remains deny-only debt.

## Protected call graph

The composed normal-run path is:

1. Admit private non-symlink source files, the exact runtime file/symlink
   inventory, exact source/runtime/artifact digests, state root, and
   absolute protected tools.
2. Bind Buildkite pipeline/build/job/commit/step/queue/retry identity.
3. Request the fixed in-memory staging OIDC JWT.
4. Resolve exact NetBox devices 1/2/6/7 and load only OpenBao credentials 6/7.
5. Load the digest-bound CML CA, authenticate with protected CML credentials,
   and reject any existing NCDP staging realization.
6. Derive exact Terraform variables, initialize only the installed ephemeral
   root, save and structurally approve the exact ten-create plan, and apply
   that exact plan file.
7. Read allowlisted outputs, record private recovery metadata, and verify the
   disposable four-node/four-link realization without exposing Day-0.
8. Save, approve, and apply only the lifecycle update.
9. Perform bounded `.30/.31` management readiness and stable run-scoped SSH
   host-trust acquisition.
10. Freshly resolve NetBox and run installed NCDP read-only planning for Cisco
    `GigabitEthernet2` and Junos `ge-0/0/2`.
11. Inspect protected Terraform state in `finally`, destroy an exact full or
    partial subset with an exact saved plan, prove CML UUID/title absence and
    empty state, then retire only that run directory.

Raw Terraform JSON, saved plans, state, device output, Day-0, credentials,
tokens, JWTs, CA material, and environment data are never emitted.

## Partial failure and recovery

A failed create or start is not blindly retried. `terraform state list` must be
empty or a subset of the exact ten addresses. A foreign address stops cleanup
and retains state. For a valid subset, the destroy plan must delete exactly the
observed addresses and is applied by saved filename. Cleanup or independent
absence ambiguity retains state and the bounded evidence records primary and
cleanup failure separately.

Trusted-operator recovery accepts only a canonical Buildkite build UUID,
derives `bk-<uuid>` and its state directory, loads the private recovery record,
requires exact source/bundle/manifest agreement, never creates or starts, and
performs only exact-subset cleanup and independent absence proof. Recovery also
accepts the post-destroy crash window with already-empty state: it performs no
destroy, proves UUID/title or provisional title absence, rechecks empty state,
and only then retires the run. A different installed bundle fails closed.

## Local, tool, and runtime isolation

Private files must be absolute regular non-symlinks outside the checkout,
correctly owned, private, bounded in size, and nonempty where required.
Privileged executables are absolute, outside checkout, non-symlink, not
group/world writable, and version-bound where applicable. Terraform remains
exactly 1.15.8. The Terraform environment is constructed from an allowlist and
does not inherit caller `TF_LOG`, `CML2_TOKEN`, NetBox, OpenBao, or device
credentials.

The B3-2B2 construction contract uses a versioned installation root with
separate `source/`, `runtime/`, and `artifacts/` authorities plus
`source-files.json`, `runtime-files.json`, and the final manifest. It uses exact
Python 3.12, a built wheel,
`uv.lock`, frozen production dependency export with hashes, and a private
non-editable virtual environment. The protected source inventory includes only
required controller, adapter, read-only Ansible, Terraform, and bootstrap
assets. It also includes the packaging-declared `README.md` and the controller's
direct `buildkite_policy.py` import; tests and `.git` are excluded. The admitted
uv install compiles bytecode before runtime inventory. The exact base Python
interpreter path and digest are manifest authority, and only the venv's exact
`bin/python` symlink may cross the runtime boundary to that interpreter.
B3-2B1 installed nothing into standing
agent paths. Runtime admission rejects unexpected files, digest or mode drift,
controller-entry-point replacement, source symlinks, and runtime symlinks that
escape the admitted runtime.

The actual reduced-source construction was exercised in a private temporary
directory: it built the project wheel, exported and installed all hash-frozen
production dependencies without an editable install, created the real
`ncdp-protected-staging-controller` entry point, ran `--help` outside the
checkout without bytecode suppression, and produced an identical runtime
inventory before and after startup. No standing path was used.

Creation-attempt state is explicit. A pre-create admission failure may retire
only an empty local run without claiming CML ownership. Once create was
attempted, retirement requires empty Terraform state plus exact UUID/title
absence when trusted outputs exist, or exact run-title absence when they do
not. Successful subset cleanup uses the latter proof. Terraform initialization
has its own bounded `TERRAFORM_INIT` evidence classification.

B3-2B2 has a hard admission prerequisite: checkout-controlled validation and
protected staging must have demonstrably different OS filesystem authority. It
must discover validation, staging, and deploy UIDs plus ownership/ACLs for every
proposed protected root. If validation and staging share a Unix UID or
equivalent read/write authority, B3-2B2 must stop before installation; path
separation and private modes alone are insufficient.

## Evidence and negative proof

Evidence schema 2 is an explicit non-secret allowlist for immutable Buildkite
identity, source/bundle/manifest digests, staging/homolog IDs, `.30/.31`,
credential references, disposable UUIDs, structural action counts, bounded
timings/attempts, outcomes, and enumerated failure codes. Primary and cleanup
failure are independent; provider exception text is not serialized.

This increment made zero NetBox, OpenBao, CML, external Terraform-state,
Buildkite external-configuration, LaunchAgent, or device/session/configuration
mutation. It requested no real JWT, read no real secret, opened no device
session, performed no staging or protected delivery, installed no external
runtime, did not start B4, and did not progress 11A or 11B.
