#!/usr/bin/env python3
"""Install a protected staging source bundle after merged-main review."""

from __future__ import annotations

import argparse
import stat
from pathlib import Path
from uuid import UUID

from network_change_delivery.protected_staging_install import (
    StandingInstallationAuthority,
    SubprocessRuntimeBuildRunner,
    install_source_bundle,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--destination", required=True, type=Path)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--controller-identity", required=True)
    parser.add_argument("--controller-url", required=True)
    parser.add_argument("--buildkite-pipeline-id", required=True, type=UUID)
    parser.add_argument("--netbox-url", required=True)
    parser.add_argument("--openbao-url", required=True)
    parser.add_argument("--cml-ca-pem-sha256", required=True)
    parser.add_argument("--uv-executable", required=True, type=Path)
    parser.add_argument("--uv-cache-directory", required=True, type=Path)
    parser.add_argument("--installation-authority", required=True, type=Path)
    arguments = parser.parse_args()
    authority_path = arguments.installation_authority
    metadata = authority_path.lstat()
    authority_boundary = Path("/private/var/db/ncdp-staging/authority")
    if (
        not authority_path.is_absolute()
        or authority_path.is_symlink()
        or not authority_path.is_file()
        or metadata.st_uid != 0
        or stat.S_IMODE(metadata.st_mode) != 0o400
        or not authority_path.resolve(strict=True).is_relative_to(
            authority_boundary.resolve(strict=True)
        )
    ):
        parser.error("installation authority must be a root-owned 0400 regular file")
    parent = authority_path.resolve(strict=True).parent
    while True:
        parent_metadata = parent.lstat()
        if parent_metadata.st_uid != 0 or stat.S_IMODE(parent_metadata.st_mode) & 0o022:
            parser.error("installation authority parent is not root-controlled")
        if parent == authority_boundary.resolve(strict=True):
            break
        parent = parent.parent
    authority = StandingInstallationAuthority.model_validate_json(
        authority_path.read_text(encoding="utf-8")
    )
    install_source_bundle(
        arguments.source,
        arguments.destination,
        arguments.commit,
        arguments.controller_identity,
        arguments.controller_url,
        arguments.buildkite_pipeline_id,
        arguments.netbox_url,
        arguments.openbao_url,
        arguments.cml_ca_pem_sha256,
        SubprocessRuntimeBuildRunner(
            arguments.uv_executable, arguments.uv_cache_directory
        ),
        arguments.uv_executable,
        authority,
        standing=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
