# CML Terraform environments

The active lab trust boundary is reviewed merged `main` plus separate staging
credentials. `ephemeral/` and `modules/managed-pair/` remain the exact
ten-resource disposable target. The schema-4 checkout-independent host/runtime
design is retained as deferred production-hardening reference, not an active
prerequisite. Persistent brownfield CML remains outside Terraform authority.

ADR 0023 separates the Terraform implementations in this directory:

- `ephemeral/` plus `modules/managed-pair/` is the target staging structure. It
  owns one disposable lab, four nodes, four links, and one lifecycle resource:
  exactly ten resources. Its Cisco/Junos data-plane link is staging integration
  topology, not a claim about brownfield live wiring.
- the directory root plus `modules/twin/` is the frozen historical
  pre-ADR-0023 operator-twin implementation. It remains for migration and
  historical recovery continuity. It is neither live/reference authority nor
  authorized for execution during the migration.

Terraform never owns or adopts the brownfield live/reference lab. Phase B3-1
changes only the static staging graph. The checked-in orchestration still uses
historical devices 1/2 authority and is intentionally fail closed after B2;
B3-2A supplies the non-executing protected devices 6/7 controller and bundle
contract. B3-2B owns installation from exact merged main, and B4 owns cutover.

## Historical operator-twin contract

Before Phase B3-1, the historical operator/local and ephemeral staging roots
both consumed `modules/twin`. That module discovered controller metadata, the
unique `System Bridge` connector and accepted images, and realized the
five-node, six-link, 13-resource topology used by Increment 8 staging
acceptance. Historical evidence below describes that pre-B3-1 implementation.
Its only device configuration was the ADR 0013 personal-lab minimum Day-0
exception; it never owned NCDP-managed network intent or production
configuration.

In the current tree, only the frozen operator/local root continues to consume
`modules/twin`. The current `ephemeral/` root consumes `modules/managed-pair`
and represents the ADR 0023 ten-resource staging target. The historical root
and module remain only for migration and recovery continuity; they are neither
live/reference authority nor authorized for execution.

The future protected controller may execute `ephemeral/` only from an
agent-owned, digest-verified installation outside every checkout. Its immutable
manifest binds the exact ten Terraform addresses and lifecycle-only update
address. It stores sensitive saved plans only under protected run state,
validates their structural actions, and applies the exact admitted plan. The
B3-2A repository content is installation source, not installed authority.
It does not yet create a runnable isolated runtime; B3-2B must construct and
verify that runtime from the exact accepted merged-main source before admission.

B3-2B1 now supplies the repository-side executable composition and tests its
isolated Python 3.12 wheel/lock/runtime contract in temporary directories. It
does not install a standing runtime. B3-2B2 still owns exact merged-main
construction, host tool/collection admission, and external installation.
The B3-2B2B0-R correction models that future installation as root-owned
immutable authority consumed by an exact non-root staging service identity;
only run state is service-owned. It also requires protected libssh and rejects
runtime native linkage into user-controlled Homebrew or checkout paths.

ADR 0014 makes normal staging ephemeral: absent, fresh create, first boot,
readiness and validation, sanitized evidence, complete destroy, then proven
absence. The final Increment 8D twin was destroyed and the external state has no
managed resources. At that time, both the operator and ephemeral roots
permitted complete destruction because a fresh, explicitly admitted realization
must be retired before another fixed-address twin can start. Exact graph
validation and the safe Terraform UI bound that operation; neither root relied on
`prevent_destroy`, and both consumed `modules/twin`. Do not treat a normal
create-oriented plan against the empty operator state as drift.

Terraform `1.15.8` and `CiscoDevNet/cml2` `0.9.3-beta1` are exact contracts.
Provider connection, token, and trusted PEM content are supplied only through
`CML2_ADDRESS`, `CML2_TOKEN`, and `CML2_CACERT`. TLS verification remains
enabled, provider `skip_verify` is explicitly `false`, and token caching is
explicitly disabled in HCL.

The deterministic canvas places the external connector at `(-400, -200)`, the
management switch at `(-150, -200)`, `core-02` at `(100, -400)`,
`edge-junos-01` at `(400, -200)`, and `core-03` at `(700, -400)`. Tags control
only CML lifecycle staging; they are not NCDP targeting metadata.

`core-02` renders `modules/twin/bootstrap/cat8000v.tftpl`, and
`edge-junos-01` renders `modules/twin/bootstrap/vjunos-router.tftpl`, into their
respective `cml2_node.configuration` fields. Their templates contain only
hostname, management addressing, the local lab account, SSH, NETCONF, and
minimum platform prerequisites. Neither contains an actual credential or
address in Git, NCDP-managed interface intent, routing, or interface
descriptions. `core-03` receives a separate deterministic, non-secret
`cat8000v-unmanaged.tftpl` bootstrap containing only its existing role hostname
and serial-console platform prerequisite. This prevents the IOS XE first-boot
setup/security dialog without inventing a management identity or credential.

Every live plan or apply requires these runtime inputs:

- `TF_VAR_core_02_bootstrap_hostname` from the freshly verified NetBox device;
- `TF_VAR_core_02_bootstrap_management_cidr` from its NetBox primary IPv4;
- `TF_VAR_core_02_bootstrap_username` from the existing OpenBao credential; and
- `TF_VAR_core_02_bootstrap_password` from the same OpenBao credential.
- `TF_VAR_edge_junos_01_bootstrap_hostname` from the freshly verified NetBox
  device;
- `TF_VAR_edge_junos_01_bootstrap_management_cidr` from its NetBox primary
  IPv4;
- `TF_VAR_edge_junos_01_bootstrap_username` from the existing non-root OpenBao
  credential; and
- `TF_VAR_edge_junos_01_bootstrap_password_hash`, derived locally from the
  OpenBao password with SHA-512 crypt and fixed salt `ncdpedgejunos01`.

The username, password, and password-hash variables are sensitive, required,
and have no defaults. Terraform receives the IOS XE plaintext lab password but
only the deterministic verifier for Junos; the Junos plaintext remains in
OpenBao and the bounded operator process. Do not create a credential-bearing
`.tfvars` file. Keep runtime values in a bounded operator process, and do not
save a Terraform plan. This personal-lab exception deliberately copies
credential material into external Terraform state and CML Day-0 storage. Those
stores are privileged operational data; this is not a production
secret-handling pattern.

Junos initial configuration requires root authentication. The vJunos template
uses a committed, one-purpose Ed25519 public key whose private half was discarded
immediately after generation, configures no root password, and explicitly sets
root SSH login to `deny`. The existing non-root OpenBao identity is created as a
built-in `super-user` for personal-lab manageability. This is not a production
least-privilege or credential-distribution design.

Live local state belongs outside the repository on encrypted operator storage
with restrictive permissions. During a run it contains rendered credential-
bearing bootstrap; after successful Increment 8D destruction the retained
external state contains no managed twin resources.
Supply its path only while initializing the backend, for example through the
operator-controlled `NCDP_CML_TF_STATE_PATH` environment variable. Failed
destruction must retain its run-scoped state; state is retired only after
successful destruction is independently proven.

The lifecycle input has no default, so omission fails closed and every live
plan or apply requires explicit operator intent. With provider `0.9.3-beta1`,
first creation requires explicit `DEFINED_ON_CORE`; this creates the topology
without booting it. A future `STARTED` request is an explicit operational start,
and `STOPPED` is valid only after an operational start. `DEFINED_ON_CORE` after
operational use is a reset/wipe semantic, not a steady-state stop, and is not a
routine staging transition. Increment 8E will replace persistent reuse with a
build-scoped create/validate/destroy lifecycle.

CI performs formatting, backend-free initialization with the committed lockfile
in read-only mode, and static validation. CI receives no CML credentials and
does not run a plan or contact the controller.

### Mandatory safe live Terraform UI

Provider `0.9.3-beta1` copies complete node objects, including stored Day-0
configuration, into the non-sensitive computed `cml2_lifecycle.nodes` snapshot.
Terraform state remains privileged under ADR 0013, and human-readable live
Terraform plan/apply can expose credential-bearing configuration during a
lifecycle change. Direct `terraform show`, `terraform show -json`, `terraform
state show`, and human-readable live plan/apply are therefore not accepted
operator paths for this root.

Every live plan or apply must use Terraform's machine-readable JSON UI and the
stdlib-only structural allowlist renderer, with shell pipeline failure
propagation enabled:

```shell
set -o pipefail
terraform -chdir=infrastructure/cml plan -json -input=false |
  python scripts/terraform_cml_safe_ui.py

set -o pipefail
terraform -chdir=infrastructure/cml apply -json -auto-approve -input=false |
  python scripts/terraform_cml_safe_ui.py
```

The apply form is permitted only after a separately reviewed safe JSON plan.
The JSON stream must never be captured or passed through `tee`; saved Terraform
plans remain prohibited. Do not enable `TF_LOG` or provider debug logging. This
boundary contains operator output; it does not remove credential material from
external Terraform state or CML stored Day-0 configuration.

Increment 8D-2B live acceptance replaced core-02 and its two UUID-bound links,
then proved zero-console first boot and restart, strict SSH, TCP/830, and
existing NCDP read-only planning. A recreated link may remain
`DEFINED_ON_CORE` until its endpoint interfaces run; normalizing that link to
`STOPPED` is a bounded CML operational lifecycle action and never authorizes
device configuration.

Increment 8D later proved exact 740-byte vJunos Day-0 delivery and manageable
fresh first boot, then recreated the complete 13-resource twin. A restart of the
same accepted vJunos UUID did not restore management connectivity; it was not
fixed. ADR 0014 therefore makes restart persistence an explicit scenario test,
not a normal staging-readiness requirement. The whole twin was subsequently
destroyed through an exact 13-resource Terraform graph.

### Ephemeral run contract

The target ephemeral root requires a unique non-secret `staging_run_id`, explicit
`lifecycle_state`, and every authority-derived Day-0 input. It has no
credential defaults or committed tfvars. Initialize it with a unique backend
path supplied externally for that run:

```shell
terraform -chdir=infrastructure/cml/ephemeral init \
  -backend-config="path=<protected-run-directory>/terraform.tfstate"
```

The state directory and file permissions are orchestration responsibilities.
State contains ADR 0013 credential copies, must never be shared or uploaded as
a Buildkite artifact, and must be retained after failed destruction. Retire it
only after successful Terraform destroy and independent CML absence proof.
Increment 8E-2 provides `scripts/run_ephemeral_cml_staging.py` as the local
operator entry point. It requires explicit `--run-id`, `--run-directory`, and
sanitized `--evidence` destinations. It admits one fixed-address run, resolves
authority inputs once, performs only safe-rendered live Terraform operations,
attempts destroy in `finally`, independently verifies CML absence, and retires
only the exact run directory after empty state is proven. Failed destroy or
absence verification retains the directory for recovery. Increment 8E-3 invokes
the same engine from serialized Buildkite staging. Its build-UUID run has an
isolated backend, `TF_DATA_DIR`, and strict SSH trust beneath an agent-owned
persistent state root; only sanitized evidence is uploaded. The retained-state
operator command can only destroy an exact known run and retires state only
after independent absence proof.

CML Configuration Customizer Scripts must already be enabled for vJunos Day-0.
This controller-global prerequisite is verified outside Terraform and is not
configured by either root.
