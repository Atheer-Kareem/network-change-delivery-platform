# Protected staging controller contract — Phase B3-2A

## Authority and scope

This non-executing increment starts from merged main
`a8914f0a024e9e87637fda536f7af293493ac3d1` and natural merged-main Buildkite
build 190 (`PASSED`). ADR 0023 and the B3-1 exact ten-resource managed-pair
graph remain authoritative.

The external `com.buildkite.ncdp-staging` LaunchAgent remained disabled and
unloaded. Pipeline `cml-staging` remained exactly `if: "false"`, and protected
delivery retained its independent explicit-false condition. No staging or
protected-delivery execution was authorized.

## Trust zones and manifest

The checkout is source under test and receives no CML credential or bearer,
Terraform provider/state authority, protected NetBox reader, OpenBao
administrative/live-secret capability, or protected environment. The future
installed bundle is a versioned, private, digest-verified copy of the reviewed
controller and Terraform managed-pair source outside every checkout. External
agent-owned configuration supplies the immutable authority manifest,
credentials, and protected state root.

Manifest schema 1 rejects unknown fields and binds:

- source commit, bundle digest, controller digest, and every protected file;
- staging device 6 `stg-core-02`, `.30`, homolog 1 `core-02`, and its exact
  interface, status, role, platform, OpenBao role, and secret reference;
- staging device 7 `stg-edge-junos-01`, `.31`, homolog 2
  `edge-junos-01`, and the corresponding exact authority;
- live-deny IDs 1/2/3 and `.14/.15/.20`;
- the controller identity, `System Bridge`, CAT8000V
  `cat8000v-17-18-02`, vJunos `vjunos-router-23-2r1-15`, and denied brownfield
  lab UUID `09605569-0468-4fc4-8684-beb5a1342b9c`;
- the exact B3-1 ten-resource graph and lifecycle-only update address.

The related NetBox object filter remains convenience metadata, not protected
authorization. The independent resolver reads stable IDs 1/2/6/7 and validates
exact identity, environment, homolog, status, role, platform, interface,
primary IP, matching device type, and an exactly empty staging tag collection.
Live homologs must remain `active`, use the compatible platform, have
environment `live`, and have no homolog value. For each live ID the resolver
also issues a bounded native `cf_ncdp_live_homolog=<id>` query and requires one
complete result containing only its accepted staging ID. Zero, duplicate,
alternate, malformed, or paginated reverse mappings fail closed. The normal live
`NetBoxInventoryProvider` is unchanged and is not weakened to admit `staged`
devices.

## Protected execution contracts

The staging secret authority accepts only device 6 with
`ncdp-buildkite-staging-device-6` and
`openbao:kv-v2:ncdp/devices/6/ssh`, or device 7 with the corresponding 7 role
and reference. IDs 1/2/3, arbitrary IDs, roles, and references fail closed. The
administrative configurator now describes only the standing B2 roles/policies
6/7; it was not executed and OpenBao was not mutated.

The controller requests its in-memory Buildkite JWT with the exact accepted
audience, 300-second lifetime, `pipeline_id` subject claim, and explicit
`build_id` claim. These values are constants rather than caller inputs.

The protected CML client accepts credentials only through protected controller
configuration and keeps its minted bearer in memory. CML 2.10 discovery first
requires `GET /api/v0/labs` to return only unique UUID strings, then reads each
exact `/api/v0/labs/<uuid>` detail and validates identity and title. Dictionary
or mixed lab lists and malformed details fail with sanitized errors. Admission rejects the
brownfield lab, unexplained NCDP staging realizations, alternate endpoints,
connector, or images. It never cleans an unknown or foreign lab.

Terraform source, backend path, and run identity are controller-owned. Bundle
and state roots must be absolute, private, non-symlink, outside the checkout,
correctly owned, and digest exact. Create admits exactly ten creates, start
admits exactly the lifecycle update, and destroy admits exactly ten deletes.
Each phase writes a mode-`0600` sensitive saved plan under protected run state,
parses only its address/action structure, and applies that exact plan file. Raw
Terraform JSON, values, state, plan files, Day-0, and credentials are never
evidence or terminal output. Cleanup is bounded to the exact run, state,
installed graph, and recorded non-brownfield disposable realization.

Evidence uses an explicit allowlist for immutable Buildkite identity, installed
digests, staging/homolog IDs, `.30/.31`, credential references, disposable CML
identifiers, structural action counts, outcomes, timings, and sanitized failure
codes. Secret values, tokens, raw provider bodies, configuration, state, plans,
and environment dumps are excluded.

## Installation and migration state

The source-bundle installer contract requires a clean exact `main` checkout whose HEAD and
`origin/main` match the authorized merged commit, copies only the reviewed
controller/Terraform/bootstrap/runtime source to a new private external bundle,
and writes per-file SHA-256 inventory plus the external manifest. Tests execute
it only in temporary directories.

Nothing was installed under staging-agent configuration, data, hook, or state
paths in B3-2A, and no runnable standing protected controller exists. B3-2B
must construct and verify the isolated executable runtime from the exact
reviewed and Buildkite-passed merged commit before installation admission,
validate the standing reader and external configuration, and keep execution
frozen. B4 separately owns agent-hook cutover and re-enable. The protected
controller never imports or executes checkout Python, shell wrappers, or
Terraform while privileged.

## Verification and negative proof

Focused tests cover strict manifest validation, exact NetBox resolution and
failure cases, live/OpenBao denial, CML admission, exact Terraform phase
allowlists, saved-plan-to-apply binding, bundle/state integrity, cleanup bounds,
evidence redaction, installer source admission, and migration freezes.

This increment made zero CML, NetBox, OpenBao, external Terraform-state,
Buildkite external-configuration, LaunchAgent, device-session/configuration,
Oxidized, AuditStore, or observability mutation. It performed no Terraform live
operation, staging execution, protected delivery, or external protected
installation. B4 did not start; 11A remains paused and 11B did not start.
