#!/usr/bin/env bash
set +x
set -euo pipefail
umask 077
exec uv run --frozen python scripts/buildkite/profiled_delivery.py
