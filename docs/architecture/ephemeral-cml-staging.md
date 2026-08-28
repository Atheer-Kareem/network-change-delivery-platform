# Ephemeral CML staging architecture

## Scope

ADR 0023 preserves the ephemeral lifecycle but changes its future authority
inputs: staging will use separate NetBox identities, management addressing,
credentials, and preferably an isolated management network. The current
operator root, shared live addresses, and five-node/six-link topology remain
migration-era implementation. Terraform has no authority over the brownfield
live/reference lab.

Increment 8E-1 provides the static Terraform foundation for ADR 0014.
Increment 8E-2 adds and locally accepts a reusable Python orchestration boundary
and thin operator entry point. Increment 8E-3 invokes that same boundary from a
serialized Buildkite step with dedicated workload, NetBox, and CML identities;
it does not fork the lifecycle or add network writes.

The normal lifecycle is absent, fresh create at `DEFINED_ON_CORE`, first boot
through `STARTED`, readiness, NCDP staging validation, sanitized evidence,
Terraform destroy, and independently proven absence. `STOPPED` is available
when operationally useful but is not an unconditional destroy prerequisite.
Same-realization restart is not part of normal readiness; reboot behavior is an
explicit scenario test.

## Terraform ownership

The current layout below is historical implementation authority until Phase B
of ADR 0023. The target layout has Terraform roots only for staging and explicit
scenarios, with reusable structure centered on a two-router homolog pair. There
will be no Terraform live root and no ordinary operator-twin environment.

There are two root modules and one shared child module:

```text
infrastructure/cml/                 operator/local root
  modules/twin/                     shared realization module
  ephemeral/                        build/run-scoped staging root
```

Each root owns `cml2_lab.twin`. Terraform lifecycle meta-arguments cannot be
controlled safely by a runtime boolean, so this boundary preserves
`prevent_destroy = true` in the operator root while the ephemeral root remains
intentionally destroyable. Both roots pass their lab ID and required authority
inputs to `modules/twin`, which owns connector/image discovery, five nodes, six
links, deterministic placement, Day-0 rendering, staging tags, update triggers,
and `cml2_lifecycle.twin`. No state migration blocks exist because Increment 8D
destroyed every managed object and left the operator state empty before the
refactor.

The child module exposes only controller/image/connector observations,
lifecycle state, and node/link UUID maps keyed by stable topology roles. Roots
may expose the disposable lab UUID and title. No output contains rendered
configuration, username, password, verifier, OpenBao material, or CML token.
CML UUIDs and tags identify realization and staging order only; they are not
NetBox identity or NCDP targeting authority.

## Run identity and serialized admission

The ephemeral root requires `staging_run_id` with no default. It is a non-secret
1-40 character lowercase ASCII identifier containing only letters, digits, and
hyphens and beginning with a letter or digit. The lab title is
`NCDP Staging <run-id>`, making one realization attributable to one run without
changing device targeting. Buildkite derives it as
`bk-${BUILDKITE_BUILD_ID}` from the immutable build UUID.

The fixed NetBox-authoritative management addresses `192.168.4.14` and
`192.168.4.20` require one admitted CML staging run at a time. Initial Buildkite
integration must use a dedicated staging concurrency group. Parallel twins are
blocked until an isolated management-network and addressing design is accepted.

ADR 0023 supersedes this shared-live-address design after Phase B. Phase B-0
accepted the fallback architecture: staging will use separate stable NetBox
objects and distinct addresses through the existing CML `System Bridge` on the
reachable `192.168.4.0/24` management fabric. This is identity, address, and
credential separation on a shared L2 and failure domain, not network isolation.
It avoids unproven controller VLAN/bridge, host-route, and NAT/PAT changes.

Shared-fabric staging requires defense in depth: protected staging identity and
address allowlists, dynamic canonical-live endpoint denial, separate
credentials, exact connector binding, pre-create collision observation,
post-boot identity validation, finally-style cleanup, and concurrent live-health
evidence. Phase B1-1 found no NetBox Prefix object or authoritative external
DHCP range for the `/24`, so exact staging addresses remain unselected until
prefix and allocator authority are established. Network silence is never IPAM
authority.

## State lifecycle and secret boundary

Each run initializes `infrastructure/cml/ephemeral` with its own externally
selected local backend path, conceptually:

```text
<protected run directory>/<run-id>/terraform.tfstate
```

No path is committed or hard-coded. The orchestrator owns restrictive parent
and file modes and encrypted-host-storage admission. State is never shared
between runs and must never be uploaded as a Buildkite artifact. Under ADR 0013
it contains credential-bearing Day-0 copies and is privileged operational data.

Finally-style cleanup attempts complete Terraform destruction after success and
failure once managed resources exist. A failed or ambiguous destroy therefore
retains the exact run state and its `TF_DATA_DIR`. State may be retired only
after Terraform destroy succeeds, an independent CML query proves the title and
every recorded realization UUID absent, and `terraform state list` is empty.
Increment 8E-2
implements this guarded retirement for a caller-supplied run directory; it
never deletes shared caches.

The structured evidence schema preserves primary validation failure separately
from cleanup failure and allowlists only structural identities, stable authority
references, timings, and outcomes. It excludes credentials, rendered configs,
state, tokens, raw device configuration, and raw provider exception bodies.

All future live plan, apply, lifecycle, and destroy operations must use
Terraform's JSON UI piped directly through `scripts/terraform_cml_safe_ui.py`.
Raw JSON, saved plans, `tee`, `TF_LOG`, human-readable apply/show, and state
payload display remain prohibited because the provider lifecycle snapshot can
surface node configuration through computed non-sensitive fields.

## Controller prerequisite

CML Configuration Customizer Scripts must already be enabled for vJunos Day-0
processing. This is a controller-global infrastructure prerequisite verified
outside Terraform. Neither root attempts to configure it.

Every router in the STARTED topology must boot unattended. The unmanaged
`core-03` role therefore receives a non-secret minimal CAT8000V startup
configuration containing only its established role hostname and platform
console prerequisite. It carries no management address or credential authority;
its staging readiness boundary is the CML `BOOTED` state. This avoids the IOS XE
17.18 initial setup/security dialog without expanding NetBox or OpenBao scope.

TCP readiness can precede vendor CLI/facts readiness. The read-only NCDP
validation boundary therefore retries only bounded provider collection failures
for three minutes, using a fresh connection each time. Inventory, policy, and
other ambiguous failures remain immediate failures; this retry never invokes a
deploy or device-write operation.

## Buildkite identities

Buildkite staging does not use ambient `NCDP_OPENBAO_ROLE_ID` or
`NCDP_OPENBAO_SECRET_ID`. It uses audience `urn:ncdp:openbao:staging` and
separate device-scoped staging roles rather than the deployment identity. The
deployment role is bound to protected `main`, the
`deploy-gate` step, approval semantics, and device-specific write workflow;
reusing it would conflate staging infrastructure with production-like
deployment authorization.

The staging roles bind the immutable pipeline subject and exact staging step,
map build commit, branch, build, and job identity for application verification,
and issue one-use tokens with no default policy. Their policies read only the two exact
personal-lab device credential paths required for Day-0. NCDP should validate
all mapped claims before credential access. A trusted agent-owned command hook
rejects fork PRs and commands other than the exact staging wrapper before
checkout code can use staging credentials. Zone 1 quality jobs remain
unprivileged.

NetBox access uses a dedicated read-only token supplied by the protected
staging agent's secret mechanism, never a repository value or artifact. CML
authentication prefers a dedicated regular staging credential. The personal
CML license rejects creation of additional users, so acceptance uses the
existing personal-controller operator login to mint one process-memory bearer
while rejecting ambient `CML2_TOKEN`. This is a platform limitation, not a
least-privilege claim. Controller-global customizer changes and device writes
remain outside staging. See
[Buildkite ephemeral CML staging operations](buildkite-ephemeral-cml-staging-operations.md).
