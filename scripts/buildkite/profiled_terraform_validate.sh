#!/usr/bin/env bash
set -euo pipefail

readonly ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
readonly TERRAFORM_ROOT="${ROOT}/infrastructure/cml/profiled-staging"

terraform -chdir="${TERRAFORM_ROOT}" fmt -check
terraform -chdir="${TERRAFORM_ROOT}" init -backend=false -input=false -lockfile=readonly
terraform -chdir="${TERRAFORM_ROOT}" validate
