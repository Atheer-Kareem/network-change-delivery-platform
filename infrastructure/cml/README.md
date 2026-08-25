# CML Terraform digital twin

This directory contains the protected operator/local root, the reusable
`modules/twin` realization module, and the intentionally destroyable
`ephemeral` staging root. Each root owns its CML lab. The shared module discovers
controller metadata, the unique `System Bridge` connector, accepted images,
five nodes, six links, and explicit lifecycle. Its only device configuration is
the ADR 0013 personal-lab minimum Day-0 exception; it never owns NCDP-managed
network intent or production configuration.

ADR 0014 makes normal staging ephemeral: absent, fresh create, first boot,
readiness and validation, sanitized evidence, complete destroy, then proven
absence. The final Increment 8D twin was destroyed and the external state has no
managed resources. The operator root retains `prevent_destroy = true`; the
ephemeral root has no such guard because complete destroy is its normal success
path. Both consume `modules/twin`. Do not treat a normal create-oriented plan
against the empty operator state as drift.

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
respective `cml2_node.configuration` fields. Each template contains only
hostname, management addressing, the local lab account, SSH, NETCONF, and
minimum platform prerequisites. Neither contains an actual credential or
address in Git, NCDP-managed interface intent, routing, or interface
descriptions. `core-03` retains explicit empty configuration.

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

The ephemeral root requires a unique non-secret `staging_run_id`, explicit
`twin_lifecycle_state`, and every NetBox/OpenBao-derived Day-0 input. It has no
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
Increment 8E-1 adds no automatic state deletion and no live staging job.

CML Configuration Customizer Scripts must already be enabled for vJunos Day-0.
This controller-global prerequisite is verified outside Terraform and is not
configured by either root.
