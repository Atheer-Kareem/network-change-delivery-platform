"""Offline installation source for a reviewed protected staging bundle."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import subprocess
from pathlib import Path
from typing import Final

from network_change_delivery.protected_staging import (
    EXPECTED_TERRAFORM_ADDRESSES,
    CMLAuthority,
    ProtectedStagingError,
    ProtectedStagingManifest,
    StagingTargetAuthority,
)

PROTECTED_SOURCE_FILES: Final[tuple[str, ...]] = (
    "pyproject.toml",
    "uv.lock",
    "src/network_change_delivery/__init__.py",
    "src/network_change_delivery/buildkite_identity.py",
    "src/network_change_delivery/buildkite_staging.py",
    "src/network_change_delivery/inventory.py",
    "src/network_change_delivery/models.py",
    "src/network_change_delivery/protected_staging.py",
    "src/network_change_delivery/protected_staging_controller.py",
    "src/network_change_delivery/secrets.py",
    "scripts/terraform_cml_safe_ui.py",
    "infrastructure/cml/ephemeral/.terraform.lock.hcl",
    "infrastructure/cml/ephemeral/outputs.tf",
    "infrastructure/cml/ephemeral/provider.tf",
    "infrastructure/cml/ephemeral/topology.tf",
    "infrastructure/cml/ephemeral/variables.tf",
    "infrastructure/cml/ephemeral/versions.tf",
    "infrastructure/cml/modules/managed-pair/bootstrap/cat8000v.tftpl",
    "infrastructure/cml/modules/managed-pair/bootstrap/vjunos-router.tftpl",
    "infrastructure/cml/modules/managed-pair/data.tf",
    "infrastructure/cml/modules/managed-pair/outputs.tf",
    "infrastructure/cml/modules/managed-pair/topology.tf",
    "infrastructure/cml/modules/managed-pair/variables.tf",
    "infrastructure/cml/modules/managed-pair/versions.tf",
)


def verify_merged_source(source: Path, expected_commit: str) -> None:
    """Require an exact, clean, non-detached main checkout before installation."""
    commands = {
        "head": ["git", "rev-parse", "HEAD"],
        "branch": ["git", "branch", "--show-current"],
        "status": ["git", "status", "--porcelain", "--untracked-files=all"],
        "origin": ["git", "rev-parse", "origin/main"],
    }
    values: dict[str, str] = {}
    for name, command in commands.items():
        result = subprocess.run(
            command, cwd=source, check=False, capture_output=True, text=True
        )
        if result.returncode != 0:
            raise ProtectedStagingError("protected installation source rejected")
        values[name] = result.stdout.strip()
    if (
        values["head"] != expected_commit
        or values["origin"] != expected_commit
        or values["branch"] != "main"
        or values["status"]
    ):
        raise ProtectedStagingError("protected installation source rejected")


def install_source_bundle(
    source: Path,
    destination: Path,
    expected_commit: str,
    controller_identity: str,
    controller_url: str,
    *,
    owner_uid: int | None = None,
) -> ProtectedStagingManifest:
    """Copy an exact reviewed source set into a new private versioned bundle."""
    verify_merged_source(source, expected_commit)
    source = source.resolve(strict=True)
    if (
        destination.exists()
        or destination.is_symlink()
        or not destination.is_absolute()
    ):
        raise ProtectedStagingError("protected installation destination rejected")
    if destination.resolve(strict=False).is_relative_to(source):
        raise ProtectedStagingError("protected installation destination rejected")
    destination.mkdir(mode=0o700, parents=False)
    if stat.S_IMODE(destination.stat().st_mode) != 0o700:
        raise ProtectedStagingError("protected installation mode rejected")
    expected_uid = os.getuid() if owner_uid is None else owner_uid
    if destination.stat().st_uid != expected_uid:
        raise ProtectedStagingError("protected installation owner rejected")
    digests: dict[str, str] = {}
    try:
        for relative in PROTECTED_SOURCE_FILES:
            source_file = source / relative
            if source_file.is_symlink() or not source_file.is_file():
                raise ProtectedStagingError(
                    "protected installation source file rejected"
                )
            target = destination / relative
            target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            shutil.copyfile(source_file, target, follow_symlinks=False)
            target.chmod(0o600)
            digests[relative] = hashlib.sha256(target.read_bytes()).hexdigest()
        inventory = json.dumps(digests, sort_keys=True, separators=(",", ":"))
        inventory_file = destination / "bundle-files.json"
        inventory_file.write_text(inventory, encoding="utf-8")
        inventory_file.chmod(0o600)
        bundle_digest = hashlib.sha256(inventory.encode()).hexdigest()
        controller_path = "src/network_change_delivery/protected_staging_controller.py"
        manifest = ProtectedStagingManifest(
            source_commit=expected_commit,
            bundle_digest=bundle_digest,
            controller_artifact_digest=digests[controller_path],
            file_digests=digests,
            cisco=_target(6),
            junos=_target(7),
            live_deny_device_ids=(1, 2, 3),
            live_deny_management_ips=(
                "192.168.4.14",
                "192.168.4.15",
                "192.168.4.20",
            ),
            cml=CMLAuthority(
                controller_identity=controller_identity,
                controller_url=controller_url,
            ),
            terraform_addresses=tuple(sorted(EXPECTED_TERRAFORM_ADDRESSES)),
            lifecycle_update_address=(
                "module.managed_pair.cml2_lifecycle.managed_pair"
            ),
        )
        manifest_file = destination / "authority-manifest.json"
        manifest_file.write_text(
            manifest.model_dump_json(indent=2) + "\n", encoding="utf-8"
        )
        manifest_file.chmod(0o600)
        return manifest
    except Exception:
        raise


def _target(device_id: int) -> StagingTargetAuthority:
    if device_id == 6:
        values = (
            "stg-core-02",
            "cisco-ios-xe",
            "GigabitEthernet1",
            "192.168.4.30",
            1,
            "core-02",
        )
    elif device_id == 7:
        values = (
            "stg-edge-junos-01",
            "juniper-junos",
            "fxp0",
            "192.168.4.31",
            2,
            "edge-junos-01",
        )
    else:
        raise ProtectedStagingError("protected installation target rejected")
    name, platform, interface, ip, homolog_id, homolog_name = values
    return StagingTargetAuthority(
        device_id=device_id,
        name=name,
        environment="staging",
        status="staged",
        role_slug="ncdp-staging",
        platform_slug=platform,
        management_interface=interface,
        management_ip=ip,
        live_homolog_id=homolog_id,
        live_homolog_name=homolog_name,
        openbao_role=f"ncdp-buildkite-staging-device-{device_id}",
        credential_reference=f"openbao:kv-v2:ncdp/devices/{device_id}/ssh",
    )
