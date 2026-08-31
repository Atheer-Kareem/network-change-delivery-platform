# Buildkite ephemeral CML staging operations

> **Temporary Detour B pause:** the `cml-staging` pipeline step and the complete
> protected-delivery group are commented out together. Quality validation,
> Terraform static validation, and PR Batfish candidate assurance remain active.
> B3-5 will re-enable staging and protected delivery together after Terraform
> realizes all four profiled devices. The implementation and historical
> acceptance below remain intact; staging has not been removed.

## Trusted agent boundary

The `cml-staging` step runs on a dedicated self-hosted `ncdp-staging` queue with
concurrency one in `ncdp/cml-ephemeral-staging`. Automatic and manual retries
are disabled. A retry is also rejected before identity or CML access. The
immutable Buildkite build UUID derives `bk-${BUILDKITE_BUILD_ID}`; build number
is not an identity.

The staging agent must install a copy of
`scripts/buildkite/staging_agent_command_hook.sh` from reviewed `main` as an
agent-owned command hook outside all checkouts. It admits only the exact staging
step, queue, and repository command and rejects a pull request whose source
repository differs from the canonical pipeline repository. This external hook
is essential: pipeline OIDC identity does not make PR-controlled code trusted.
Fork PRs retain unprivileged validation and Batfish coverage but cannot use
staging credentials. A runtime-affecting fork PR therefore cannot satisfy the
trusted CML merge gate directly; a maintainer must reproduce or adopt its commit
in the canonical repository and obtain a new trusted run.

An agent-owned `staging.env` file supplies, outside pipeline YAML:

- `NCDP_STAGING_STATE_ROOT`: persistent, agent-owned, absolute, non-symlink,
  outside the checkout, and mode `0700` or stricter;
- `NCDP_NETBOX_URL` and dedicated read-only `NCDP_STAGING_NETBOX_TOKEN`;
- `NCDP_OPENBAO_URL`;
- `CML2_ADDRESS`, PEM `CML2_CACERT`, and dedicated
  `NCDP_CML_STAGING_USERNAME` / `NCDP_CML_STAGING_PASSWORD`.

Ambient AppRole, `NCDP_NETBOX_TOKEN`, `CML2_TOKEN`, and direct device
credentials are rejected. State lives at
`<state-root>/ephemeral/<run-id>/`, survives job failure, and is never an
artifact. The filesystem should be encrypted because Terraform state contains
ADR 0013 Day-0 credential copies.

The credential file is deliberately not an `environment` hook. The trusted
agent `command` hook first validates the queue, exact command, and PR origin;
only then, after repository pre-command hooks have finished, does it source the
protected file and execute the exact wrapper. Checkout-controlled hooks never
receive staging credentials before admission.

## Workload identities

The job requests one five-minute Buildkite JWT with audience
`urn:ncdp:openbao:staging`, immutable pipeline UUID in `sub`, and explicit
`build_id`. The application validates pipeline, build, commit, branch, step,
job, queue, and retry context. It uses the JWT only in memory for one exact
login per admitted device:

- `ncdp-buildkite-staging-device-1` receives only
  `ncdp-buildkite-staging-device-1-read`;
- `ncdp-buildkite-staging-device-2` receives only
  `ncdp-buildkite-staging-device-2-read`;
- `ncdp-buildkite-staging-device-8` receives only
  `ncdp-buildkite-staging-device-8-read`; and
- `ncdp-buildkite-staging-device-9` receives only
  `ncdp-buildkite-staging-device-9-read`.

Each policy reads only `ncdp/data/devices/<id>/ssh`. Tokens are one-use, have no
default policy, and expire within 300 seconds. Configure and read back this
repository-owned state from a trusted shell using environment-only `BAO_TOKEN`:

```shell
uv run python scripts/openbao/configure_buildkite_staging.py
```

The tool verifies the existing NCDP-owned `jwt/` mount and backend and never
alters deployment roles. NetBox uses a distinct token limited to device,
interface, IP-address, tag, and protection-metadata reads. CML 2.10 exposes lab
ownership and sharing, but the personal license rejects creation of additional users. This
environment therefore cannot supply the preferred regular staging account and
uses the existing personal-controller operator login to mint one in-memory
bearer per run. This is an explicit platform limitation, not a claim of narrow
CML authorization. The driver rejects ambient `CML2_TOKEN`; controller settings
remain outside staging.

## Execution and evidence

The preserved pipeline block defines one `Ephemeral CML staging · create →
validate → destroy` job and calls only
`scripts/buildkite/ephemeral_staging.sh`. During B3-3 that block is commented
out and creates no job. When B3-5 restores it, the wrapper verifies
job/checkout identity, pipes the JWT to the existing Python driver, and uploads
only `staging-evidence/staging-run.json`. The authoritative state machine remains
`network_change_delivery.ephemeral_staging.run_staging_lifecycle`; Buildkite log
presentation does not split lifecycle or cleanup ownership across jobs.

When enabled, runtime-relevant pull requests make `cml-staging` wait for both
`validation-complete` and successful `pr-batfish-assurance`. This orders the
cheaper offline candidate-model check before CML resource creation. On main the
PR-only Batfish dependency is skipped and satisfied, so CML still fans out in
parallel with the protected-main `batfish-assurance` branch. The staging key,
queue, trusted hook, workload identity, concurrency, and retry rules are
unchanged.

Expanded log groups identify admission/authority, Terraform create, topology
and stored Day-0 verification, lab start, device readiness, strict host trust,
Cisco and Junos read-only NCDP validation, Terraform destroy, independent
absence verification, run-scoped state retirement, and final result. Readiness
emits low-volume progress using the existing ARP, ICMP, TCP/22, and TCP/830
criteria, ten-second polling, and 1,200-second operational timeout. Cisco and
Junos phases are explicitly labelled `READ-ONLY`; neither invokes a device
write. Staging does not apply the proposed live candidate configuration; it
proves real-vendor topology, readiness, trust, and read-only NCDP provider
integration complementary to Batfish's offline candidate assurance.

Each realization gets a run-scoped `known_hosts` file for exact
`192.168.4.30` and `192.168.4.40` trust. NetBox device 1/2 primary addresses
remain `.14/.20`; staging verifies the secondary addresses are assigned to the
same authoritative management interfaces before creating the lab. SSH and
NETCONF remain strict; no human trust file or earlier-build key is used. Staging
performs read-only NCDP planning/validation and never invokes `ncdp deploy`.

Evidence contains only job binding, disposable CML IDs, stable NetBox identity,
credential references, timings, and outcomes. Tokens, credentials, Day-0,
device configuration, provider bodies, and state are excluded. The full JSON is
no longer dumped into ordinary logs. A strict typed renderer validates the
regular non-symlink evidence and publishes a bounded browser annotation with
allowlisted lifecycle, readiness, read-only validation, cleanup, and retirement
facts. Raw failures, credential references, node/link IDs, NetBox object IDs,
Day-0, state, and provider detail are not rendered.

Successful annotation evidence requires the exact four-node/four-link topology,
complete readiness and validation observations for both routers, all lifecycle
outcomes passed, and no primary or cleanup failure. Failed evidence may remain
partial while using only known roles. If staging fails, renderer, artifact, or
annotation publication failure cannot replace the primary staging status. If
staging succeeds, required evidence publication must also succeed.

## Retained-state recovery

Destroy or absence failure retains the run directory. Do not retry the job,
delete CML objects manually, or manipulate state. From a trusted operator shell
with local AppRole and the exact retained run, execute:

```shell
uv run python scripts/recover_ephemeral_cml_staging.py \
  --run-id <bk-build-uuid> \
  --run-directory <state-root>/ephemeral/<bk-build-uuid> \
  --evidence <protected-recovery-evidence.json>
```

Recovery refuses empty, unknown, foreign, or extra state; reconstructs inputs;
plans only deletion of the retained managed subset; destroys; independently
proves the title and recorded CML UUIDs absent; requires empty state; and only
then retires the directory. It cannot create or start staging infrastructure.
