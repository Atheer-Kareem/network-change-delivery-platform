"""Offline installation source for a reviewed protected staging bundle."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import subprocess
from collections.abc import Callable, Mapping, Sequence
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
    execution_tool_version_runner,
    inspect_combined_native_dependency_graph,
    native_dependency_graph_sha256,
    terraform_version_runner,
    validate_combined_native_dependency_graph,
    validate_root_owned_bootstrap_source,
    validate_root_owned_executable,
    validate_root_owned_immutable_tree,
    validate_root_owned_service_directory,
    validate_system_rooted_directory,
)

CANONICAL_REPOSITORY = "Atheer-Kareem/network-change-delivery-platform"
CANONICAL_ORIGIN_URL = (
    "https://github.com/Atheer-Kareem/network-change-delivery-platform.git"
)
SYSTEM_GIT = Path("/usr/bin/git")

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
    "src/network_change_delivery/protected_staging_install.py",
    "src/network_change_delivery/protected_staging_installer_cli.py",
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
    uv_cache_root: Path
    build_sdk_root: Path
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
    build_sdk_identity: str

    @model_validator(mode="after")
    def exact_paths(self) -> StandingInstallationAuthority:
        if (
            not self.protected_python.is_absolute()
            or not self.uv_cache_root.is_absolute()
            or not self.build_sdk_root.is_absolute()
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

    def native_dependency(self, name: str) -> NativeDependencyAuthority:
        matches = tuple(
            value for value in self.native_dependencies if value.name == name
        )
        if len(matches) != 1:
            raise ProtectedStagingError("standing native dependency authority invalid")
        return matches[0]

    def build_environment(self) -> dict[str, str]:
        """Derive the sole native build environment from admitted roots."""
        libssh = Path(self.native_dependency("libssh").root)
        if libssh != Path("/private/var/db/ncdp-staging/authority/native/libssh"):
            raise ProtectedStagingError("protected libssh build authority rejected")
        return {
            "SDKROOT": str(self.build_sdk_root),
            "CPATH": str(libssh / "include"),
            "LIBRARY_PATH": str(libssh / "lib"),
            "LDFLAGS": f"-L{libssh / 'lib'}",
            "CPPFLAGS": f"-I{libssh / 'include'}",
            "PKG_CONFIG_PATH": str(libssh / "lib/pkgconfig"),
        }


class RuntimeBuildRunner(Protocol):
    def run(self, arguments: Sequence[str], *, cwd: Path) -> None: ...


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

    def validate_authority(self, authority: StandingInstallationAuthority) -> None:
        """Require the builder to match the reviewed standing authority exactly."""
        expected = {
            "PATH": str(Path(authority.uv.path).parent),
            "UV_CACHE_DIR": str(authority.uv_cache_root),
            "UV_NO_PROGRESS": "1",
            **authority.build_environment(),
        }
        if self._uv != Path(authority.uv.path) or self._environment != expected:
            raise ProtectedStagingError("protected runtime builder authority rejected")

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


GitRunner = Callable[
    [Sequence[str], Path, Mapping[str, str]], subprocess.CompletedProcess[str]
]


def _system_git_runner(
    arguments: Sequence[str], cwd: Path, environment: Mapping[str, str]
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(arguments),
        cwd=cwd,
        env=dict(environment),
        check=False,
        capture_output=True,
        text=True,
    )


def verify_merged_source(
    source: Path,
    expected_commit: str,
    *,
    standing: bool = False,
    service_identity: ServiceIdentityAuthority | None = None,
    git_runner: GitRunner = _system_git_runner,
) -> None:
    """Require exact canonical merged source with sanitized system Git authority."""
    if standing:
        if service_identity is None:
            raise ProtectedStagingError("protected bootstrap identity missing")
        validate_root_owned_bootstrap_source(source, expected_commit, service_identity)
    environment = {
        "PATH": "/usr/bin:/bin",
        "HOME": "/var/empty",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_CONFIG_COUNT": "0",
        "GIT_OPTIONAL_LOCKS": "0",
    }
    prefix = (
        str(SYSTEM_GIT),
        "-c",
        "core.fsmonitor=false",
        "-c",
        "core.hooksPath=/dev/null",
    )
    commands = {
        "head": (*prefix, "rev-parse", "HEAD"),
        "branch": (*prefix, "branch", "--show-current"),
        "status": (*prefix, "status", "--porcelain", "--untracked-files=all"),
        "origin_head": (*prefix, "rev-parse", "origin/main"),
        "origin_url": (*prefix, "remote", "get-url", "origin"),
    }
    values: dict[str, str] = {}
    for name, command in commands.items():
        result = git_runner(command, source, environment)
        if result.returncode != 0:
            raise ProtectedStagingError("protected installation source rejected")
        values[name] = result.stdout.strip()
    if (
        values["head"] != expected_commit
        or values["origin_head"] != expected_commit
        or values["origin_url"] != CANONICAL_ORIGIN_URL
        or (not standing and values["branch"] != "main")
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
    verify_merged_source(
        source,
        expected_commit,
        standing=standing,
        service_identity=(
            installation_authority.service_identity if standing else None
        ),
    )
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
        authority_root = Path("/private/var/db/ncdp-staging/authority")
        if (
            installation_authority.uv_cache_root != authority_root / "cache/uv"
            or Path(installation_authority.uv.path).parent != authority_root / "tools"
            or not installation_authority.protected_python.resolve(
                strict=True
            ).is_relative_to(authority_root / "tools")
            or installation_authority.ansible_collections_root
            != authority_root / "ansible"
            or any(
                Path(value.root).parent != authority_root / "native"
                for value in installation_authority.native_dependencies
            )
        ):
            raise ProtectedStagingError("standing installation layout rejected")
        if not isinstance(runtime_runner, SubprocessRuntimeBuildRunner):
            raise ProtectedStagingError("standing runtime builder rejected")
        runtime_runner.validate_authority(installation_authority)
        validate_root_owned_executable(
            uv_executable,
            source,
            installation_authority.service_identity,
            installation_authority.uv,
            observed_version=execution_tool_version_runner(uv_executable, "uv"),
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
        for tool in (
            installation_authority.buildkite_agent,
            installation_authority.terraform,
            installation_authority.openssl,
            installation_authority.ssh_keyscan,
            installation_authority.ssh_keygen,
        ):
            validate_root_owned_executable(
                Path(tool.path),
                source,
                installation_authority.service_identity,
                tool,
                observed_version=(
                    terraform_version_runner(Path(tool.path), ())
                    if tool is installation_authority.terraform
                    else execution_tool_version_runner(
                        Path(tool.path), Path(tool.path).name
                    )
                ),
            )
        validate_root_owned_service_directory(
            installation_authority.uv_cache_root,
            source,
            installation_authority.service_identity,
        )
        validate_system_rooted_directory(installation_authority.build_sdk_root, source)
        if (
            str(installation_authority.build_sdk_root)
            != installation_authority.build_sdk_identity
        ):
            raise ProtectedStagingError("protected SDK authority rejected")
        validate_root_owned_immutable_tree(
            installation_authority.ansible_collections_root,
            source,
            installation_authority.service_identity,
            installation_authority.ansible_inventory_sha256,
            expected_collections=installation_authority.ansible_collections,
        )
        admitted_native_roots: list[Path] = []
        for dependency in installation_authority.native_dependencies:
            root = Path(dependency.root)
            validate_root_owned_immutable_tree(
                root,
                source,
                installation_authority.service_identity,
                dependency.inventory_sha256,
            )
            try:
                observed_version = (
                    (root / "VERSION").read_text(encoding="utf-8").strip()
                )
            except OSError:
                raise ProtectedStagingError(
                    "protected native dependency version rejected"
                ) from None
            if observed_version != dependency.version:
                raise ProtectedStagingError(
                    "protected native dependency version rejected"
                )
            admitted_native_roots.append(root.resolve(strict=True))
        for value, digest in installation_authority.protected_native_files.items():
            path = Path(value)
            if (
                not any(
                    path.resolve(strict=True).is_relative_to(root)
                    for root in admitted_native_roots
                )
                or hashlib.sha256(path.read_bytes()).hexdigest() != digest
            ):
                raise ProtectedStagingError("protected native file authority rejected")
    if (
        destination.exists()
        or destination.is_symlink()
        or not destination.is_absolute()
    ):
        raise ProtectedStagingError("protected installation destination rejected")
    if standing:
        install_parent = Path("/private/var/db/ncdp-staging/authority/install")
        if destination.parent != install_parent:
            raise ProtectedStagingError("standing installation destination rejected")
        validate_root_owned_service_directory(
            install_parent, source, installation_authority.service_identity
        )
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
            native_scopes = {
                "runtime": runtime,
                "python": installation_authority.protected_python,
                "openssl-tool": Path(installation_authority.openssl.path),
                "terraform": Path(installation_authority.terraform.path),
                "buildkite-agent": Path(installation_authority.buildkite_agent.path),
                "uv-install-time": Path(installation_authority.uv.path),
                **{
                    dependency.name: Path(dependency.root)
                    for dependency in installation_authority.native_dependencies
                },
            }
            native_graph = inspect_combined_native_dependency_graph(native_scopes)
            if set(native_graph) != set(native_scopes):
                raise ProtectedStagingError("protected native dependency scope changed")
            validate_combined_native_dependency_graph(
                native_graph,
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
            admission = native_dependency_graph_sha256(native_graph)
            for immutable_root in (source_root, runtime, destination / "artifacts"):
                _apply_immutable_ownership(
                    immutable_root, installation_authority.service_identity.service_gid
                )
            final_native_graph = inspect_combined_native_dependency_graph(native_scopes)
            if set(final_native_graph) != set(native_scopes):
                raise ProtectedStagingError("protected native dependency scope changed")
            validate_combined_native_dependency_graph(
                final_native_graph,
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
            if native_dependency_graph_sha256(final_native_graph) != admission:
                raise ProtectedStagingError(
                    "protected native dependency admission changed"
                )
        else:
            admission = native_dependency_graph_sha256({"runtime": {}})
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
            canonical_repository=CANONICAL_REPOSITORY,
            canonical_origin_url=CANONICAL_ORIGIN_URL,
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
            native_dependency_admission_sha256=admission,
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
