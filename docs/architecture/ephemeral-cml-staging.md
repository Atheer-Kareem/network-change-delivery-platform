# Ephemeral CML staging architecture

## Scope

Increment 8E-1 provides the static Terraform foundation for ADR 0014.
Increment 8E-2 adds and locally accepts a reusable Python orchestration boundary
and thin operator entry point. Increment 8E-3 will invoke that same boundary in
Buildkite after separate identity and external acceptance; no live Buildkite
staging step exists yet.

The normal lifecycle is absent, fresh create at `DEFINED_ON_CORE`, first boot
through `STARTED`, readiness, NCDP staging validation, sanitized evidence,
Terraform destroy, and independently proven absence. `STOPPED` is available
when operationally useful but is not an unconditional destroy prerequisite.
Same-realization restart is not part of normal readiness; reboot behavior is an
explicit scenario test.

## Terraform ownership

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
changing device targeting. Increment 8E-3 will derive this value
deterministically from stable Buildkite build/run identity.

The fixed NetBox-authoritative management addresses `192.168.4.14` and
`192.168.4.20` require one admitted CML staging run at a time. Initial Buildkite
integration must use a dedicated staging concurrency group. Parallel twins are
blocked until an isolated management-network and addressing design is accepted.

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

## Future Buildkite identities

Buildkite staging must not use ambient `NCDP_OPENBAO_ROLE_ID` or
`NCDP_OPENBAO_SECRET_ID`. Increment 8E-3 should use Buildkite OIDC with a new
staging-specific audience, OpenBao JWT role, and policies rather than reuse the
deployment identity role. The deployment role is bound to protected `main`, the
`deploy-gate` step, approval semantics, and device-specific write workflow;
reusing it would conflate staging infrastructure with production-like
deployment authorization.

The staging JWT role should bind the immutable pipeline subject plus exact
build commit, branch policy, staging step key, build identity, and job identity,
with short TTL and no default policy. Its policy should read only the two exact
personal-lab device credential paths required for Day-0. NCDP should validate
all mapped claims before credential access. PR trust and branch eligibility for
a credential-bearing staging step require an explicit 8E-3 decision; Zone 1
quality jobs remain unprivileged.

NetBox access should use a dedicated read-only token supplied by the protected
staging agent's secret mechanism, never a repository value or artifact. CML
authentication should likewise be a dedicated short-lived staging credential
delivered only to the serialized staging step, with address and trusted CA
supplied separately. CML administrative capability, controller-global
customizer changes, and deployment-device write capability are outside that
identity. Concrete OpenBao roles/policies and Buildkite wiring are deferred to
8E-3.
