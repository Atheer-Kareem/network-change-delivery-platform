# Increment 8B Terraform/CML foundation acceptance

Status: read-only foundation and speculative plan accepted; completion is
effective after review and merge.

## Reproducible toolchain

| Contract | Accepted evidence |
| --- | --- |
| Terraform CLI | `1.15.8` exact |
| CML2 provider | `CiscoDevNet/cml2` `0.9.3-beta1` exact |
| Lock platforms | `darwin_arm64`, `linux_arm64`, `linux_amd64` |
| Provider verification | Self-signed provider packages, key ID `A97E6292972408AB`, with registry checksums recorded by `terraform providers lock` |
| Terraform CI image | `hashicorp/terraform:1.15.8@sha256:7ae513256f7ce67879e218ae8593d6fbe216ec9e123abe6c94e4e10704857963` |
| CI image version | Terraform `1.15.8`, verified by running the pinned image |

The Buildkite quality step mounts the checkout read-only, uses executable
ephemeral storage under `/tmp` for `TF_DATA_DIR`, receives no CML environment
inputs, and runs only version, formatting, backend-disabled locked
initialization, and validation commands. It does not plan or contact CML.

## Read-only plan evidence

The root contains only `cml2_system`, `cml2_connector`, and `cml2_images` data
sources. Output preconditions require exactly one connector labelled `System
Bridge` and exactly one image matching each accepted ID. No connector device
name was assumed before the plan.

| Observation | Accepted value |
| --- | --- |
| Controller version | `2.10.0+build.13` |
| System Bridge match count | 1 |
| System Bridge resolved device name | `bridge0` |
| CAT8000V image match count / ID | 1 / `cat8000v-17-18-02` |
| vJunos image match count / ID | 1 / `vjunos-router-23-2r1-15` |

The exact host Terraform executable initialized the local backend using only the
operator-supplied external path and then ran one unsaved speculative plan. TLS
verification remained enabled. `skip_verify`, token caching, dynamic provider
configuration, and named configurations remained explicitly false.

## Validation and safety result

- Terraform formatting: **PASSED**.
- Credential-free `init -backend=false -input=false -lockfile=readonly`:
  **PASSED**.
- Terraform validation: **PASSED**.
- Speculative read-only plan: **PASSED**.
- Managed-resource actions: **0 create, 0 update, 0 delete**.
- Saved plan: **NO**.
- Live Terraform state created: **NO**.
- Terraform state backup created: **NO**.
- CML mutation or lifecycle change: **NO**.
- CML token persisted: **NO**.

No JWT, certificate PEM, username, password, request headers, state path, or
other credential material is recorded here. NetBox, OpenBao, network devices,
and the Buildkite deployment runtime were not accessed. The accepted legacy CML
lab was not modified.
