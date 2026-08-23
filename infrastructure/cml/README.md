# CML Terraform digital twin

This root defines the separately owned Terraform CML digital twin. Increment
8C-1 is plan-only: the topology is reviewed through an unsaved speculative plan,
and no managed CML resource has been created yet. The root discovers controller
metadata, the uniquely labelled `System Bridge` connector, and the two accepted
image definitions before it can plan the lab, five nodes, six links, and explicit
lifecycle. It must never be used for network-device configuration.

Terraform `1.15.8` and `CiscoDevNet/cml2` `0.9.3-beta1` are exact contracts.
Provider connection, token, and trusted PEM content are supplied only through
`CML2_ADDRESS`, `CML2_TOKEN`, and `CML2_CACERT`. TLS verification remains
enabled, provider `skip_verify` is explicitly `false`, and token caching is
explicitly disabled in HCL. Do not add credential variables or `.tfvars` files.

The deterministic canvas places the external connector at `(-400, -200)`, the
management switch at `(-150, -200)`, `core-02` at `(100, -400)`,
`edge-junos-01` at `(400, -200)`, and `core-03` at `(700, -400)`. Tags control
only CML lifecycle staging; they are not NCDP targeting metadata.

Each router explicitly uses `configuration = ""` so provider/CML default
bootstrap content cannot be returned for a null attribute and persisted into
Terraform state. The empty value is a state-secrecy control, not managed network
intent or proof of successful future boot. Never place credentials or functional
network bootstrap in this field, and do not use CML **Bootstrap Lab** or an
equivalent default-configuration generator in the accepted Terraform workflow.
Runtime state-free bootstrap remains deferred to Increment 8D.

Live local state belongs outside the repository on encrypted operator storage.
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
