#!/usr/bin/env bash
set -euo pipefail

readonly ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
readonly TERRAFORM_ROOT="${ROOT}/infrastructure/cml/profiled-staging"
readonly TF_DATA_DIR="$(mktemp -d "${TMPDIR:-/tmp}/ncdp-profiled-tf.XXXXXX")"
export TF_DATA_DIR
trap 'rm -rf -- "${TF_DATA_DIR}"' EXIT

terraform -chdir="${TERRAFORM_ROOT}" fmt -check
terraform -chdir="${TERRAFORM_ROOT}" init -backend=false -input=false -lockfile=readonly
terraform -chdir="${TERRAFORM_ROOT}" validate
