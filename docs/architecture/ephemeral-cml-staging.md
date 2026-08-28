# Ephemeral CML staging architecture

## Scope

ADR 0023 preserves the ephemeral lifecycle but changes its authority
inputs: staging will use separate NetBox identities, management addressing,
credentials, and preferably an isolated management network. Terraform has no
authority over the brownfield live/reference lab. Phase B3-1 establishes the
static two-router target graph. Phase B3-2A adds the non-executing protected
controller and installation-source contracts; installation and external
admission remain deferred to B3-2B, and execution remains fail closed.

Phase B3-2B1 composes that contract into the complete repository-side
executable lifecycle. B3-2B2B0-R advances the authority to manifest schema 4
with separately inventoried root-owned reviewed
source and generated executable-runtime authority, exact object-ID admission,
digest-bound CML trust, exact saved-plan application, partial-state cleanup,
read-only device validation, recovery, and sanitized evidence. It remains
repository-only. B3-2B2 must construct and admit the exact merged-main isolated
runtime externally before B4 may cut over the protected hook.

B3-2B2 must prove an OS-principal/ACL boundary between checkout-controlled
validation and protected staging. If they share filesystem authority, including
one Unix UID, installation is prohibited.

Schema 4 binds the exact non-root staging UID/GID and empty supplementary
groups while immutable configuration, credentials, source, runtime, artifacts,
tools, Ansible collections, and native dependencies remain root-owned. Only
build and run state is service-owned. The controller uses a fixed configuration
path independent of `HOME`, construction requires an exact protected Python,
and native admission rejects linkage into Homebrew, checkout, user-home, or
temporary authority. Protected libssh is an explicit supply-chain dependency.

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

The directory contains a target staging path and a frozen historical path:

```text
infrastructure/cml/                 frozen historical operator root
  modules/twin/                     frozen historical 13-resource module
  modules/managed-pair/             target two-router staging module
  ephemeral/                        build/run-scoped target staging root
```

The target root owns `cml2_lab.staging` and passes its lab ID and explicit
inputs to `modules/managed-pair`. The module owns System Bridge and image
discovery, a management switch, one Cisco router, one Junos router, four links,
Day-0 rendering, staging tags, and `cml2_lifecycle.managed_pair`. Together the
root and module contain exactly one lab, four nodes, four links, and one
lifecycle resource: ten managed resources. There is no baseline `core-03`.
The Cisco/Junos link is staging integration topology; a staging homolog is a
platform and automation-role homolog, not an exact live-topology clone.

The root and `modules/twin` retain the historical five-node, six-link,
13-resource operator-twin implementation. They are not staging target
authority, not live/reference authority, and not authorized for execution
during migration. No state migration is needed because the staging state root
contains no managed realization.

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
evidence. Phase B1-1 found no NetBox Prefix object and could not establish the
external allocator boundary, so it correctly proposed no staging addresses.
The operator subsequently established that the LAN is static/manual and has no
DHCP pool or reservations; a bounded follow-up created the authoritative
`192.168.4.0/24` Prefix and recorded the known infrastructure and live
allocations. A separate read-only candidate discovery found no conflicting
authority or bounded secondary evidence for `.30`/`.31`, and the operator then
selected them. Phase B1-2 created stable NetBox staging devices 6 and 7,
`stg-core-02` and `stg-edge-junos-01`, assigned `.30` and `.31`, classified the
canonical pair as `live` and staging pair as `staging`, and bound each staging
device explicitly to its live homolog. The staging devices are `staged`, have a
dedicated role, and carry no live selector tags. Network silence was not IPAM
authority. Phase B2 created separate credentials and exact device-read
policies/JWT roles for staging devices 6/7 and retired the historical staging
roles/policies that read live devices 1/2. Live secrets and deployment authority
were preserved. Terraform/Buildkite consumption remains later Phase B work.

The checked-in consumer still selects historical devices 1/2, so it is
intentionally fail-closed after B2. No `cml-staging` execution is authorized
until B3/B4 migrate the consumer. A reviewed Buildkite migration execution guard
or freeze is required before the first B3 source or Terraform commit is pushed.
Phase B2-G provides that prerequisite through a disabled and unloaded external
staging LaunchAgent plus independent explicit-false pipeline conditions for
legacy staging and protected delivery. B4 alone owns reviewed removal and agent
re-enable after the devices 6/7 consumer is migrated.

Phase B3-2A divides the future staging path into three trust zones. The checkout
contains source under test but receives no CML, Terraform-state, NetBox-reader,
OpenBao, or protected-environment authority. A versioned agent-owned bundle,
installed outside every checkout from an exact clean merged-main commit, owns
the controller and reviewed ten-resource Terraform source. Agent-owned external
configuration owns the immutable authority manifest, state root, and
credentials. The controller rejects checkout Terraform, arbitrary authority
paths, ambient live inventory credentials, live device IDs/addresses, and the
brownfield lab UUID.

The manifest binds staging devices 6/7 and homologs 1/2, `.30/.31`, exact
OpenBao roles/references, System Bridge and image definitions, the ten-address
Terraform graph, source commit, and per-file bundle digests. The staging
resolver reads devices by stable ID and validates exact status, role, platform,
matching homolog device type, interface, primary IP, environment, an exactly
empty staging tag set, and unique reverse homolog mapping through bounded native
custom-field queries; the live
`NetBoxInventoryProvider` remains unchanged. Privileged Terraform uses only
saved, mode-`0600` plans whose sanitized structural actions match the phase
allowlist, then applies that exact plan.

B3-2A does not create a runnable standing controller or install or activate a
bundle. B3-2B must construct and verify the isolated executable runtime from
exact merged authority and validate external authority while preserving the freeze.
B4 separately owns command-hook cutover and agent re-enable.

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

Historical staging used Terraform's JSON UI piped through
`scripts/terraform_cml_safe_ui.py`. The protected B3-2A contract instead keeps
raw plan JSON inside trusted parsing, writes a sensitive saved plan in the
protected run directory, structurally admits it, and applies that exact file.
Raw JSON, saved plans, `tee`, `TF_LOG`, human-readable apply/show, and state
payload display remain prohibited because the provider lifecycle snapshot can
surface node configuration through computed non-sensitive fields.

## Controller prerequisite

CML Configuration Customizer Scripts must already be enabled for vJunos Day-0
processing. This is a controller-global infrastructure prerequisite verified
outside Terraform. Neither root attempts to configure it.

The target managed pair contains no `core-03` node, link, lifecycle trigger, or
output. Historical operator-twin evidence and code retain their three-router
facts without making that topology part of the ADR 0023 staging baseline.

TCP readiness can precede vendor CLI/facts readiness. The read-only NCDP
validation boundary therefore retries only bounded provider collection failures
for three minutes, using a fresh connection each time. Inventory, policy, and
other ambiguous failures remain immediate failures; this retry never invokes a
deploy or device-write operation. The checkout-controlled historical driver
still resolves devices 1/2 and remains deliberately unusable. B3-2A supplies a
separate protected devices 6/7 contract without making checkout code privileged.

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
staging-device credential paths required for Day-0. NCDP should validate
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
