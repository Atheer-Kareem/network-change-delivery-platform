# CML Terraform digital twin

This root defines the separately owned Terraform CML digital twin. Increment
8C-1 is plan-only: the topology is reviewed through an unsaved speculative plan,
and no managed CML resource has been created yet. The root discovers controller
metadata, the uniquely labelled `System Bridge` connector, and the two accepted
image definitions before it can plan the lab, five nodes, six links, and explicit
lifecycle. Its only device configuration is the personal-lab minimum Day-0
manageability exception defined by ADR 0013; it must never own NCDP-managed
network intent or production configuration.

Terraform `1.15.8` and `CiscoDevNet/cml2` `0.9.3-beta1` are exact contracts.
Provider connection, token, and trusted PEM content are supplied only through
`CML2_ADDRESS`, `CML2_TOKEN`, and `CML2_CACERT`. TLS verification remains
enabled, provider `skip_verify` is explicitly `false`, and token caching is
explicitly disabled in HCL.

The deterministic canvas places the external connector at `(-400, -200)`, the
management switch at `(-150, -200)`, `core-02` at `(100, -400)`,
`edge-junos-01` at `(400, -200)`, and `core-03` at `(700, -400)`. Tags control
only CML lifecycle staging; they are not NCDP targeting metadata.

`core-02` renders `bootstrap/cat8000v.tftpl` into
`cml2_node.core_02.configuration`. The template contains only hostname,
GigabitEthernet1 management addressing, the local lab account, SSH, NETCONF,
and their minimum prerequisites. It contains no actual credential, address,
GigabitEthernet2 intent, routing, or interface description. The other routers
retain explicit empty configuration until their own bootstrap is accepted.

Every live plan or apply requires these runtime inputs:

- `TF_VAR_core_02_bootstrap_hostname` from the freshly verified NetBox device;
- `TF_VAR_core_02_bootstrap_management_cidr` from its NetBox primary IPv4;
- `TF_VAR_core_02_bootstrap_username` from the existing OpenBao credential; and
- `TF_VAR_core_02_bootstrap_password` from the same OpenBao credential.

The username and password variables are sensitive, required, and have no
defaults. Do not create a credential-bearing `.tfvars` file. Keep all four
values in a bounded operator process, and do not save a Terraform plan. This
personal-lab exception deliberately copies the credential into external
Terraform state and CML Day-0 storage. Those stores are privileged operational
data; this is not a production secret-handling pattern.

Live local state belongs outside the repository on encrypted operator storage
with restrictive permissions. It intentionally contains the rendered core-02
bootstrap after Increment 8D-2B.
Supply its path only while initializing the backend, for example through the
operator-controlled `NCDP_CML_TF_STATE_PATH` environment variable. An 8C-1
acceptance run performs only an unsaved speculative `terraform plan`; it never
runs apply, import, destroy, or a state mutation command.

The lifecycle input has no default, so omission fails closed and every live
plan or apply requires explicit operator intent. With provider `0.9.3-beta1`,
first creation requires explicit `DEFINED_ON_CORE`; this creates the topology
without booting it. A future `STARTED` request is an explicit operational start,
and `STOPPED` is valid only after an operational start. `DEFINED_ON_CORE` after
operational use is a reset/wipe semantic, not a steady-state stop, and is
reserved for Increment 8D reset acceptance. Increment 8C-1 remains plan-only.

CI performs formatting, backend-free initialization with the committed lockfile
in read-only mode, and static validation. CI receives no CML credentials and
does not run a plan or contact the controller.
