"""Root-bootstrap-only entry point for standing protected staging installation."""

from __future__ import annotations

import argparse
import os
import stat
import sys
from pathlib import Path
from uuid import UUID

from network_change_delivery.protected_staging import ProtectedStagingError
from network_change_delivery.protected_staging_install import (
    StandingInstallationAuthority,
    SubprocessRuntimeBuildRunner,
    install_source_bundle,
)

BOOTSTRAP_RUNTIME_ROOT = Path("/private/var/db/ncdp-staging/bootstrap/runtime")
INSTALLATION_AUTHORITY_ROOT = Path("/private/var/db/ncdp-staging/authority")


def validate_bootstrap_installer_execution(
    *,
    executable: Path,
    module_file: Path,
    runtime_root: Path = BOOTSTRAP_RUNTIME_ROOT,
    metadata_reader=os.lstat,
) -> None:
    """Reject root execution of installer Python from checkout/user authority."""
    runtime = runtime_root.resolve(strict=True)
    lexical_executable = executable.absolute()
    module = module_file.resolve(strict=True)
    if (
        not lexical_executable.is_relative_to(runtime)
        or not module.is_relative_to(runtime)
        or module_file.is_symlink()
        or not module_file.is_file()
    ):
        raise ProtectedStagingError("protected installer execution authority rejected")
    for path in (runtime, module):
        metadata = metadata_reader(path)
        if metadata.st_uid != 0 or stat.S_IMODE(metadata.st_mode) & 0o022:
            raise ProtectedStagingError(
                "protected installer execution authority rejected"
            )
    executable_metadata = metadata_reader(lexical_executable)
    if executable_metadata.st_uid != 0 or (
        not stat.S_ISLNK(executable_metadata.st_mode)
        and stat.S_IMODE(executable_metadata.st_mode) & 0o022
    ):
        raise ProtectedStagingError("protected installer execution authority rejected")
    current = module.parent
    while True:
        metadata = metadata_reader(current)
        if metadata.st_uid != 0 or stat.S_IMODE(metadata.st_mode) & 0o022:
            raise ProtectedStagingError(
                "protected installer execution authority rejected"
            )
        if current == runtime:
            break
        current = current.parent
    resolved_executable = executable.resolve(strict=True)
    protected_tools_root = Path("/private/var/db/ncdp-staging/authority/tools").resolve(
        strict=True
    )
    if (
        not resolved_executable.is_file()
        or (
            not resolved_executable.is_relative_to(runtime)
            and not resolved_executable.is_relative_to(protected_tools_root)
        )
        or str(resolved_executable).startswith(
            (
                "/Users/netdevops/",
                "/opt/homebrew/",
                "/private/tmp/",
                "/private/var/folders/",
                "/tmp/",
            )
        )
        or metadata_reader(resolved_executable).st_uid != 0
        or stat.S_IMODE(metadata_reader(resolved_executable).st_mode) & 0o022
    ):
        raise ProtectedStagingError("protected installer execution authority rejected")


def _parser() -> argparse.ArgumentParser:
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
    parser.add_argument("--installation-authority", required=True, type=Path)
    return parser


def main() -> int:
    """Install only from the fixed root-owned bootstrap runtime."""
    parser = _parser()
    if any(value in {"-h", "--help"} for value in sys.argv[1:]):
        parser.parse_args()
        return 0
    try:
        validate_bootstrap_installer_execution(
            executable=Path(sys.executable), module_file=Path(__file__)
        )
    except (OSError, ProtectedStagingError) as error:
        raise SystemExit(str(error)) from None
    arguments = parser.parse_args()
    authority_path = arguments.installation_authority
    metadata = authority_path.lstat()
    if (
        not authority_path.is_absolute()
        or authority_path.is_symlink()
        or not authority_path.is_file()
        or metadata.st_uid != 0
        or stat.S_IMODE(metadata.st_mode) != 0o400
        or not authority_path.resolve(strict=True).is_relative_to(
            INSTALLATION_AUTHORITY_ROOT.resolve(strict=True)
        )
    ):
        parser.error("installation authority must be a root-owned 0400 regular file")
    parent = authority_path.resolve(strict=True).parent
    while True:
        parent_metadata = parent.lstat()
        if parent_metadata.st_uid != 0 or stat.S_IMODE(parent_metadata.st_mode) & 0o022:
            parser.error("installation authority parent is not root-controlled")
        if parent == INSTALLATION_AUTHORITY_ROOT.resolve(strict=True):
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
            Path(authority.uv.path),
            authority.uv_cache_root,
            build_environment=authority.build_environment(),
        ),
        Path(authority.uv.path),
        authority,
        standing=True,
    )
    return 0
