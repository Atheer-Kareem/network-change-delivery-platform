"""Offline installation source for a reviewed protected staging bundle."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Final, Protocol
from uuid import UUID

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
    "src/network_change_delivery/protected_staging_runtime.py",
    "src/network_change_delivery/secrets.py",
    "src/network_change_delivery/workflow.py",
    "src/network_change_delivery/ansible_adapter.py",
    "src/network_change_delivery/junos_adapter.py",
    "ansible.cfg",
    "ansible/requirements.yml",
    "ansible/collect_interface_state.yml",
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


class RuntimeBuildRunner(Protocol):
    def run(self, arguments: Sequence[str], *, cwd: Path) -> None: ...


class SubprocessRuntimeBuildRunner:
    """Run admitted uv construction commands with a minimal installer environment."""

    def __init__(
        self,
        uv_executable: Path,
        cache_directory: Path,
        *,
        build_environment: Mapping[str, str] | None = None,
    ) -> None:
        if not uv_executable.is_absolute() or not cache_directory.is_absolute():
            raise ProtectedStagingError("protected runtime builder rejected")
        self._uv = uv_executable
        admitted_build_keys = {
            "SDKROOT",
            "CPATH",
            "LIBRARY_PATH",
            "LDFLAGS",
            "CPPFLAGS",
            "PKG_CONFIG_PATH",
        }
        build_values = dict(build_environment or {})
        if set(build_values) - admitted_build_keys or any(
            not value or "\x00" in value or "\n" in value
            for value in build_values.values()
        ):
            raise ProtectedStagingError("protected runtime build environment rejected")
        self._environment = {
            "PATH": str(uv_executable.parent),
            "UV_CACHE_DIR": str(cache_directory),
            "UV_NO_PROGRESS": "1",
            **build_values,
        }

    def run(self, arguments: Sequence[str], *, cwd: Path) -> None:
        if not arguments or arguments[0] != str(self._uv):
            raise ProtectedStagingError("protected runtime build command rejected")
        result = subprocess.run(
            list(arguments),
            cwd=cwd,
            env=self._environment,
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if result.returncode != 0:
            raise ProtectedStagingError("protected runtime construction failed")


def construct_isolated_runtime(
    source: Path,
    bundle: Path,
    runner: RuntimeBuildRunner,
    *,
    uv_executable: Path,
) -> Path:
    """Construct a non-editable locked runtime under a temporary/test bundle."""
    if (
        not source.is_absolute()
        or not bundle.is_absolute()
        or bundle.is_symlink()
        or not uv_executable.is_absolute()
    ):
        raise ProtectedStagingError("protected runtime construction rejected")
    runtime = bundle / "runtime"
    wheels = bundle / "wheels"
    requirements = bundle / "production-requirements.txt"
    if runtime.exists() or wheels.exists() or requirements.exists():
        raise ProtectedStagingError("protected runtime construction rejected")
    wheels.mkdir(mode=0o700)
    uv = str(uv_executable)
    runner.run((uv, "build", "--wheel", "--out-dir", str(wheels)), cwd=source)
    runner.run(
        (
            uv,
            "export",
            "--frozen",
            "--no-dev",
            "--no-emit-project",
            "--format",
            "requirements-txt",
            "--output-file",
            str(requirements),
        ),
        cwd=source,
    )
    wheels_found = tuple(wheels.glob("network_change_delivery-*.whl"))
    if len(wheels_found) != 1 or wheels_found[0].is_symlink():
        raise ProtectedStagingError("protected runtime wheel rejected")
    wheel = wheels_found[0]
    wheel_digest = hashlib.sha256(wheel.read_bytes()).hexdigest()
    with requirements.open("a", encoding="utf-8") as stream:
        stream.write(f"\n{wheel.as_uri()} --hash=sha256:{wheel_digest}\n")
    requirements.chmod(0o600)
    runner.run((uv, "venv", "--python", "3.12", str(runtime)), cwd=bundle)
    python = runtime / "bin/python"
    runner.run(
        (
            uv,
            "pip",
            "install",
            "--python",
            str(python),
            "--require-hashes",
            "--requirements",
            str(requirements),
        ),
        cwd=bundle,
    )
    return runtime


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
    buildkite_pipeline_id: UUID,
    netbox_url: str,
    openbao_url: str,
    cml_ca_pem_sha256: str,
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
            buildkite_pipeline_id=buildkite_pipeline_id,
            source_commit=expected_commit,
            netbox_url=netbox_url,
            openbao_url=openbao_url,
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
                ca_pem_sha256=cml_ca_pem_sha256,
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
            1,
            1,
            9,
            9,
            "192.168.4.30/24",
            "192.168.4.14/24",
        )
    elif device_id == 7:
        values = (
            "stg-edge-junos-01",
            "juniper-junos",
            "fxp0",
            "192.168.4.31",
            2,
            "edge-junos-01",
            1,
            2,
            10,
            10,
            "192.168.4.31/24",
            "192.168.4.20/24",
        )
    else:
        raise ProtectedStagingError("protected installation target rejected")
    (
        name,
        platform,
        interface,
        ip,
        homolog_id,
        homolog_name,
        site_id,
        device_type_id,
        interface_id,
        ip_address_id,
        management_cidr,
        live_primary_cidr,
    ) = values
    return StagingTargetAuthority(
        device_id=device_id,
        name=name,
        site_id=site_id,
        device_type_id=device_type_id,
        environment="staging",
        status="staged",
        role_slug="ncdp-staging",
        platform_slug=platform,
        management_interface=interface,
        management_interface_id=interface_id,
        management_interface_type="1000base-t",
        management_interface_enabled=True,
        management_interface_mgmt_only=False,
        management_ip_address_id=ip_address_id,
        management_cidr=management_cidr,
        management_ip=ip,
        live_homolog_id=homolog_id,
        live_homolog_name=homolog_name,
        live_primary_cidr=live_primary_cidr,
        openbao_role=f"ncdp-buildkite-staging-device-{device_id}",
        credential_reference=f"openbao:kv-v2:ncdp/devices/{device_id}/ssh",
    )
