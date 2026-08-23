# CML Terraform foundation

This root is the read-only Increment 8B foundation for the separately owned CML
digital twin. It discovers controller metadata, the uniquely labelled `System
Bridge` connector, and the two accepted image definitions. It contains no
managed resources and must never be used for network-device configuration.

Terraform `1.15.8` and `CiscoDevNet/cml2` `0.9.3-beta1` are exact contracts.
Provider connection, token, and trusted PEM content are supplied only through
`CML2_ADDRESS`, `CML2_TOKEN`, and `CML2_CACERT`. TLS verification and the
provider's token cache remain explicitly disabled in HCL. Do not add credential
variables or `.tfvars` files.

Live local state belongs outside the repository on encrypted operator storage.
Supply its path only while initializing the backend, for example through the
operator-controlled `NCDP_CML_TF_STATE_PATH` environment variable. A normal 8B
acceptance run performs only an unsaved speculative `terraform plan`; it never
runs apply, import, destroy, or a state mutation command.

CI performs formatting, backend-free initialization with the committed lockfile
in read-only mode, and static validation. CI receives no CML credentials and
does not run a plan or contact the controller.
