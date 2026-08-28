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

from pydantic import BaseModel, ConfigDict, model_validator

from network_change_delivery.protected_staging import (
    EXPECTED_TERRAFORM_ADDRESSES,
    CMLAuthority,
    ExecutionToolAuthority,
    NativeDependencyAuthority,
    ProtectedStagingError,
    ProtectedStagingManifest,
    ServiceIdentityAuthority,
    StagingTargetAuthority,
    validate_protected_bundle,
    validate_runtime_artifacts,
    validate_runtime_inventory,
)
from network_change_delivery.protected_staging_runtime import (
    validate_macho_dependencies,
    validate_root_owned_executable,
)

PROTECTED_SOURCE_FILES: Final[tuple[str, ...]] = (
    "README.md",
    "pyproject.toml",
    "uv.lock",
    "src/network_change_delivery/__init__.py",
    "src/network_change_delivery/buildkite_identity.py",
    "src/network_change_delivery/buildkite_policy.py",
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


class StandingInstallationAuthority(BaseModel):
    """Operator-supplied authority needed before a standing install can begin."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    service_identity: ServiceIdentityAuthority
    protected_python: Path
    python_version: str
    python_sha256: str
    uv: ExecutionToolAuthority
    buildkite_agent: ExecutionToolAuthority
    terraform: ExecutionToolAuthority
    openssl: ExecutionToolAuthority
    ssh_keyscan: ExecutionToolAuthority
    ssh_keygen: ExecutionToolAuthority
    ansible_collections_root: Path
    ansible_collections: dict[str, str]
    ansible_inventory_sha256: str
    native_dependencies: tuple[NativeDependencyAuthority, ...]
    protected_native_files: dict[str, str]
    native_dependency_admission_sha256: str
    build_sdk_identity: str

    @model_validator(mode="after")
    def exact_paths(self) -> StandingInstallationAuthority:
        if (
            not self.protected_python.is_absolute()
            or self.uv.path == str(self.protected_python)
            or str(self.ansible_collections_root) == ""
            or self.python_version != "3.12"
            or len(self.python_sha256) != 64
            or any(
                character not in "0123456789abcdef" for character in self.python_sha256
            )
            or not self.protected_native_files
            or not self.build_sdk_identity
        ):
            raise ValueError("standing installation authority is invalid")
        return self


class RuntimeBuildRunner(Protocol):
    def run(self, arguments: Sequence[str], *, cwd: Path) -> None: ...


def inspect_runtime_native_dependencies(
    runtime: Path,
) -> dict[str, tuple[str, ...]]:
    """Read Mach-O dependency paths with system-protected inspection tools."""
    observed: dict[str, tuple[str, ...]] = {}
    for path in sorted(value for value in runtime.rglob("*") if value.is_file()):
        kind = subprocess.run(
            ["/usr/bin/file", "-b", str(path)],
            env={},
            check=False,
            capture_output=True,
            text=True,
        )
        if kind.returncode != 0:
            raise ProtectedStagingError("protected native inspection failed")
        if "Mach-O" not in kind.stdout:
            continue
        linked = subprocess.run(
            ["/usr/bin/otool", "-L", str(path)],
            env={},
            check=False,
            capture_output=True,
            text=True,
        )
        if linked.returncode != 0:
            raise ProtectedStagingError("protected native inspection failed")
        dependencies = tuple(
            line.strip().split(" ", 1)[0]
            for line in linked.stdout.splitlines()[1:]
            if line.strip()
        )
        observed[str(path)] = dependencies
    return observed


def _apply_immutable_ownership(root: Path, service_gid: int) -> None:
    """Finalize a standing authority tree before its inventories are emitted."""
    if os.geteuid() != 0:
        raise ProtectedStagingError("standing installation requires root authority")
    for path in sorted(
        root.rglob("*"), key=lambda value: len(value.parts), reverse=True
    ):
        if path.is_symlink():
            os.lchown(path, 0, service_gid)
        elif path.is_dir():
            path.chmod(0o550)
            os.chown(path, 0, service_gid)
        elif path.is_file():
            executable = bool(path.stat().st_mode & 0o111)
            path.chmod(0o550 if executable else 0o440)
            os.chown(path, 0, service_gid)
    root.chmod(0o750)
    os.chown(root, 0, service_gid)


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
    install_root: Path,
    runner: RuntimeBuildRunner,
    *,
    uv_executable: Path,
    protected_python: Path,
) -> Path:
    """Construct a non-editable locked runtime under a temporary/test bundle."""
    if (
        not source.is_absolute()
        or not install_root.is_absolute()
        or install_root.is_symlink()
        or not uv_executable.is_absolute()
        or not protected_python.is_absolute()
    ):
        raise ProtectedStagingError("protected runtime construction rejected")
    runtime = install_root / "runtime"
    artifacts = install_root / "artifacts"
    wheels = artifacts / "wheels"
    requirements = artifacts / "production-requirements.txt"
    if runtime.exists() or wheels.exists() or requirements.exists():
        raise ProtectedStagingError("protected runtime construction rejected")
    wheels.mkdir(mode=0o700, parents=True)
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
    runner.run(
        (uv, "venv", "--python", str(protected_python), str(runtime)),
        cwd=install_root,
    )
    runtime.chmod(0o700)
    python = runtime / "bin/python"
    runner.run(
        (
            uv,
            "pip",
            "install",
            "--compile-bytecode",
            "--python",
            str(python),
            "--require-hashes",
            "--requirements",
            str(requirements),
        ),
        cwd=install_root,
    )
    entrypoint = runtime / "bin/ncdp-protected-staging-controller"
    if entrypoint.is_symlink() or not entrypoint.is_file():
        raise ProtectedStagingError("protected controller entrypoint missing")
    for link in runtime.rglob("*"):
        if link.is_symlink():
            target = str(link.readlink())
            # Do not resolve the final symlink: this checks its lexical boundary.
            lexical = Path(os.path.abspath(link.parent / target))  # noqa: PTH100
            if not lexical.is_relative_to(runtime) and link != runtime / "bin/python":
                raise ProtectedStagingError("protected runtime symlink escapes runtime")
    return runtime


def inventory_runtime(runtime: Path) -> tuple[dict[str, dict[str, object]], str]:
    """Inventory every executable-runtime file and admitted internal symlink."""
    entries: dict[str, dict[str, object]] = {}
    for path in sorted(runtime.rglob("*")):
        relative = str(path.relative_to(runtime))
        mode = stat.S_IMODE(path.lstat().st_mode)
        if path.is_symlink():
            target = str(path.readlink())
            resolved = path.resolve(strict=True)
            # Do not resolve the final symlink: this checks its lexical boundary.
            lexical = Path(os.path.abspath(path.parent / target))  # noqa: PTH100
            entries[relative] = {
                "type": "symlink",
                "mode": mode,
                "target": target,
            }
            if not lexical.is_relative_to(runtime):
                if relative != "bin/python" or not resolved.is_file():
                    raise ProtectedStagingError(
                        "protected runtime symlink escapes runtime"
                    )
                entries[relative]["target_sha256"] = hashlib.sha256(
                    resolved.read_bytes()
                ).hexdigest()
        elif path.is_file():
            entries[relative] = {
                "type": "file",
                "mode": mode,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
    if not entries:
        raise ProtectedStagingError("protected runtime inventory is empty")
    canonical = json.dumps(entries, sort_keys=True, separators=(",", ":"))
    return entries, hashlib.sha256(canonical.encode()).hexdigest()


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
    runtime_runner: RuntimeBuildRunner,
    uv_executable: Path,
    installation_authority: StandingInstallationAuthority,
    *,
    owner_uid: int | None = None,
    standing: bool = False,
) -> ProtectedStagingManifest:
    """Copy an exact reviewed source set into a new private versioned bundle."""
    verify_merged_source(source, expected_commit)
    source = source.resolve(strict=True)
    if str(uv_executable) != installation_authority.uv.path:
        raise ProtectedStagingError("protected uv authority mismatch")
    if standing and (
        os.geteuid() != 0
        or installation_authority.protected_python.is_symlink()
        or not installation_authority.protected_python.is_file()
        or hashlib.sha256(
            installation_authority.protected_python.read_bytes()
        ).hexdigest()
        != installation_authority.python_sha256
    ):
        raise ProtectedStagingError("protected Python authority rejected")
    if standing:
        validate_root_owned_executable(
            uv_executable,
            source,
            installation_authority.service_identity,
            installation_authority.uv,
        )
        validate_root_owned_executable(
            installation_authority.protected_python,
            source,
            installation_authority.service_identity,
            ExecutionToolAuthority(
                path=str(installation_authority.protected_python),
                sha256=installation_authority.python_sha256,
                version=installation_authority.python_version,
            ),
        )
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
    source_root = destination / "source"
    source_root.mkdir(mode=0o700)
    digests: dict[str, str] = {}
    try:
        for relative in PROTECTED_SOURCE_FILES:
            source_file = source / relative
            if source_file.is_symlink() or not source_file.is_file():
                raise ProtectedStagingError(
                    "protected installation source file rejected"
                )
            target = source_root / relative
            target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            shutil.copyfile(source_file, target, follow_symlinks=False)
            target.chmod(0o600)
            digests[relative] = hashlib.sha256(target.read_bytes()).hexdigest()
        inventory = json.dumps(digests, sort_keys=True, separators=(",", ":"))
        inventory_file = destination / "source-files.json"
        inventory_file.write_text(inventory, encoding="utf-8")
        inventory_file.chmod(0o600)
        source_bundle_digest = hashlib.sha256(inventory.encode()).hexdigest()
        runtime = construct_isolated_runtime(
            source_root,
            destination,
            runtime_runner,
            uv_executable=uv_executable,
            protected_python=installation_authority.protected_python,
        )
        if standing:
            dependency_map = inspect_runtime_native_dependencies(runtime)
            validate_macho_dependencies(
                dependency_map,
                protected_native_files={
                    Path(path): digest
                    for path, digest in (
                        installation_authority.protected_native_files.items()
                    )
                },
                digest_reader=lambda path: hashlib.sha256(
                    path.read_bytes()
                ).hexdigest(),
            )
            admission = hashlib.sha256(
                json.dumps(
                    dependency_map, sort_keys=True, separators=(",", ":")
                ).encode()
            ).hexdigest()
            if admission != installation_authority.native_dependency_admission_sha256:
                raise ProtectedStagingError(
                    "protected native dependency admission changed"
                )
            for immutable_root in (source_root, runtime, destination / "artifacts"):
                _apply_immutable_ownership(
                    immutable_root, installation_authority.service_identity.service_gid
                )
        runtime_entries, runtime_digest = inventory_runtime(runtime)
        python_interpreter = (runtime / "bin/python").resolve(strict=True)
        runtime_inventory = json.dumps(
            runtime_entries, sort_keys=True, separators=(",", ":")
        )
        runtime_inventory_file = destination / "runtime-files.json"
        runtime_inventory_file.write_text(runtime_inventory, encoding="utf-8")
        runtime_inventory_file.chmod(0o440 if standing else 0o600)
        if standing:
            os.chown(
                runtime_inventory_file,
                0,
                installation_authority.service_identity.service_gid,
            )
        wheels = tuple((destination / "artifacts/wheels").glob("*.whl"))
        if len(wheels) != 1:
            raise ProtectedStagingError("protected runtime wheel rejected")
        requirements = destination / "artifacts/production-requirements.txt"
        controller_path = "src/network_change_delivery/protected_staging_controller.py"
        manifest = ProtectedStagingManifest(
            service_identity=installation_authority.service_identity,
            buildkite_pipeline_id=buildkite_pipeline_id,
            source_commit=expected_commit,
            netbox_url=netbox_url,
            openbao_url=openbao_url,
            source_bundle_digest=source_bundle_digest,
            source_inventory_sha256=hashlib.sha256(inventory.encode()).hexdigest(),
            runtime_inventory_sha256=hashlib.sha256(
                runtime_inventory.encode()
            ).hexdigest(),
            runtime_digest=runtime_digest,
            python_interpreter_path=str(python_interpreter),
            python_interpreter_sha256=hashlib.sha256(
                python_interpreter.read_bytes()
            ).hexdigest(),
            project_wheel_sha256=hashlib.sha256(wheels[0].read_bytes()).hexdigest(),
            production_requirements_sha256=hashlib.sha256(
                requirements.read_bytes()
            ).hexdigest(),
            uv=installation_authority.uv,
            buildkite_agent=installation_authority.buildkite_agent,
            terraform=installation_authority.terraform,
            openssl=installation_authority.openssl,
            ssh_keyscan=installation_authority.ssh_keyscan,
            ssh_keygen=installation_authority.ssh_keygen,
            ansible_collections_root=str(
                installation_authority.ansible_collections_root
            ),
            ansible_collections=installation_authority.ansible_collections,
            ansible_inventory_sha256=(installation_authority.ansible_inventory_sha256),
            native_dependencies=installation_authority.native_dependencies,
            protected_native_files=installation_authority.protected_native_files,
            native_dependency_admission_sha256=(
                installation_authority.native_dependency_admission_sha256
            ),
            build_sdk_identity=installation_authority.build_sdk_identity,
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
        manifest_file.chmod(0o440 if standing else 0o600)
        if standing:
            os.chown(
                manifest_file, 0, installation_authority.service_identity.service_gid
            )
            inventory_file.chmod(0o440)
            os.chown(
                inventory_file, 0, installation_authority.service_identity.service_gid
            )
            destination.chmod(0o750)
            os.chown(
                destination, 0, installation_authority.service_identity.service_gid
            )
        validate_protected_bundle(
            source_root,
            source,
            manifest,
            owner_uid=owner_uid,
            service_identity=(
                installation_authority.service_identity if standing else None
            ),
        )
        validate_runtime_inventory(
            runtime,
            source,
            manifest,
            runtime_inventory_file,
            owner_uid=owner_uid,
            service_identity=(
                installation_authority.service_identity if standing else None
            ),
        )
        validate_runtime_artifacts(
            destination,
            manifest,
            service_identity=(
                installation_authority.service_identity if standing else None
            ),
        )
        smoke = subprocess.run(
            [str(runtime / manifest.controller_entrypoint), "--help"],
            cwd=destination,
            env={},
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if smoke.returncode != 0:
            raise ProtectedStagingError("protected controller smoke failed")
        post_smoke_entries, post_smoke_digest = inventory_runtime(runtime)
        if post_smoke_entries != runtime_entries or post_smoke_digest != runtime_digest:
            raise ProtectedStagingError("protected controller mutated runtime")
        validate_runtime_inventory(
            runtime,
            source,
            manifest,
            runtime_inventory_file,
            owner_uid=owner_uid,
            service_identity=(
                installation_authority.service_identity if standing else None
            ),
        )
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
