"""Executable composition for one future protected staging lifecycle."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import socket
import ssl
import stat
import subprocess
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Literal, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from network_change_delivery.ansible_adapter import (
    AnsibleRunnerCiscoAdapter,
    ProviderReadinessError,
    verify_deployment_ansible_runtime,
)
from network_change_delivery.buildkite_identity import BuildkiteOIDCJWT
from network_change_delivery.buildkite_staging import (
    BuildkiteStagingContext,
    BuildkiteStagingSecretProvider,
)
from network_change_delivery.inventory import InventoryError
from network_change_delivery.junos_adapter import JunosPyEZAdapter
from network_change_delivery.models import (
    DesiredDescription,
    InterfaceDescriptionIntent,
    InventoryDevice,
)
from network_change_delivery.protected_staging import (
    BROWNFIELD_LAB_UUID,
    EXPECTED_TERRAFORM_ADDRESSES,
    ExecutionToolAuthority,
    ProtectedCMLClient,
    ProtectedStagingError,
    ProtectedStagingInventoryResolver,
    ProtectedStagingManifest,
    ProtectedStagingSecretAuthority,
    ProtectedStagingTarget,
    ProtectedTerraformExecutor,
    ProtectedTerraformOutputs,
    ServiceIdentityAuthority,
    admit_cml_labs,
)
from network_change_delivery.secrets import CredentialReference, DeviceCredentials
from network_change_delivery.workflow import plan_change

MAX_PROTECTED_FILE_BYTES = 1024 * 1024
PROTECTED_AUTHORITY_ROOT = Path("/private/var/db/ncdp-staging/authority")
PROTECTED_BOOTSTRAP_ROOT = Path("/private/var/db/ncdp-staging/bootstrap")


class FailureCode(StrEnum):
    """Bounded failure classifications safe for external evidence."""

    LOCAL_AUTHORITY = "LOCAL_AUTHORITY"
    INVENTORY_AUTHORITY = "INVENTORY_AUTHORITY"
    CREDENTIAL_AUTHORITY = "CREDENTIAL_AUTHORITY"
    CML_ADMISSION = "CML_ADMISSION"
    TERRAFORM_INIT = "TERRAFORM_INIT"
    TERRAFORM_CREATE = "TERRAFORM_CREATE"
    REALIZATION = "REALIZATION"
    TERRAFORM_START = "TERRAFORM_START"
    READINESS = "READINESS"
    HOST_TRUST = "HOST_TRUST"
    VALIDATION = "VALIDATION"
    CLEANUP_UNAUTHORIZED = "CLEANUP_UNAUTHORIZED"
    CLEANUP_FAILED = "CLEANUP_FAILED"
    ABSENCE_FAILED = "ABSENCE_FAILED"
    RETIREMENT_FAILED = "RETIREMENT_FAILED"
    RECOVERY_AUTHORITY = "RECOVERY_AUTHORITY"


class ProtectedOperationError(ProtectedStagingError):
    """Sanitized failure carrying only one allowlisted lifecycle classification."""

    def __init__(self, code: FailureCode) -> None:
        super().__init__(code.value)
        self.code = code


class ProtectedToolAuthority(BaseModel):
    """Exact external executables and runtime assets admitted by B3-2B2."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    buildkite_agent: Path
    terraform: Path
    terraform_version: Literal["1.15.8"] = "1.15.8"
    openssl: Path
    ssh_keyscan: Path
    ssh_keygen: Path
    ansible_collections_root: Path


@dataclass(frozen=True)
class ProcessIdentity:
    """Injectable effective process identity used during controller admission."""

    effective_uid: int
    effective_gid: int
    supplementary_gids: tuple[int, ...]


def current_process_identity() -> ProcessIdentity:
    """Return the effective identity without consulting job-controlled input."""
    return ProcessIdentity(os.geteuid(), os.getegid(), tuple(os.getgroups()))


def validate_service_identity(
    authority: ServiceIdentityAuthority,
    identity: ProcessIdentity | None = None,
) -> None:
    """Require the exact dedicated, non-root, non-validation service principal."""
    observed = current_process_identity() if identity is None else identity
    if (
        observed.effective_uid != authority.service_uid
        or observed.effective_gid != authority.service_gid
        or observed.effective_uid in {0, 501}
        or observed.supplementary_gids != authority.supplementary_gids
    ):
        raise ProtectedStagingError("protected service identity rejected")


MetadataReader = Callable[[Path], os.stat_result]

PROTECTED_SERVICE_ROOT = Path("/private/var/db/ncdp-staging")
PROTECTED_SYSTEM_PARENT = Path("/private/var/db")


def _lstat(path: Path) -> os.stat_result:
    return path.lstat()


def _validate_controlled_ancestry(
    path: Path,
    boundary: Path,
    *,
    metadata_reader: MetadataReader = _lstat,
) -> None:
    resolved = path.resolve(strict=True)
    root = boundary.resolve(strict=True)
    if resolved != root and not resolved.is_relative_to(root):
        raise ProtectedStagingError("protected path ancestry rejected")
    current = resolved if resolved.is_dir() else resolved.parent
    while True:
        metadata = metadata_reader(current)
        if metadata.st_uid != 0 or stat.S_IMODE(metadata.st_mode) & 0o022:
            raise ProtectedStagingError("protected path ancestry rejected")
        if current == root:
            break
        current = current.parent


def _validate_service_root_ancestry(
    authority: ServiceIdentityAuthority,
    *,
    service_root: Path = PROTECTED_SERVICE_ROOT,
    system_parent: Path = PROTECTED_SYSTEM_PARENT,
    metadata_reader: MetadataReader = _lstat,
) -> None:
    """Require the root-owned service entry and its controlling system parent."""
    root = service_root.resolve(strict=True)
    parent = system_parent.resolve(strict=True)
    if root.parent != parent:
        raise ProtectedStagingError("protected service root ancestry rejected")
    for path in (root, parent):
        metadata = metadata_reader(path)
        if (
            metadata.st_uid != authority.immutable_owner_uid
            or stat.S_IMODE(metadata.st_mode) & 0o022
        ):
            raise ProtectedStagingError("protected service root ancestry rejected")
    root_metadata = metadata_reader(root)
    if (
        root_metadata.st_gid != authority.service_gid
        or stat.S_IMODE(root_metadata.st_mode) != 0o750
    ):
        raise ProtectedStagingError("protected service root ancestry rejected")


def validate_root_owned_bootstrap_source(
    source: Path,
    expected_commit: str,
    authority: ServiceIdentityAuthority,
    *,
    bootstrap_root: Path = PROTECTED_BOOTSTRAP_ROOT,
    service_root: Path = PROTECTED_SERVICE_ROOT,
    system_parent: Path = PROTECTED_SYSTEM_PARENT,
    metadata_reader: MetadataReader = _lstat,
) -> Path:
    """Admit the sole root-owned canonical source class used by standing install."""
    expected = bootstrap_root / "source" / expected_commit
    if (
        not source.is_absolute()
        or source.is_symlink()
        or source.resolve(strict=True) != expected.resolve(strict=True)
    ):
        raise ProtectedStagingError("protected bootstrap source rejected")
    _validate_service_root_ancestry(
        authority,
        service_root=service_root,
        system_parent=system_parent,
        metadata_reader=metadata_reader,
    )
    _validate_controlled_ancestry(
        source.resolve(strict=True), service_root, metadata_reader=metadata_reader
    )
    for path in (source, *sorted(source.rglob("*"))):
        if path.is_symlink():
            raise ProtectedStagingError("protected bootstrap source rejected")
        metadata = metadata_reader(path)
        if (
            metadata.st_uid != authority.immutable_owner_uid
            or metadata.st_gid != authority.service_gid
            or stat.S_IMODE(metadata.st_mode) & 0o022
            or not (stat.S_ISREG(metadata.st_mode) or stat.S_ISDIR(metadata.st_mode))
        ):
            raise ProtectedStagingError("protected bootstrap source rejected")
    return source.resolve(strict=True)


def read_root_owned_service_file(
    path: Path,
    checkout: Path,
    authority: ServiceIdentityAuthority,
    *,
    authority_root: Path = PROTECTED_AUTHORITY_ROOT,
    service_root: Path = PROTECTED_SERVICE_ROOT,
    system_parent: Path = PROTECTED_SYSTEM_PARENT,
    metadata_reader: MetadataReader = _lstat,
    maximum_bytes: int = MAX_PROTECTED_FILE_BYTES,
) -> bytes:
    """Read immutable root-owned policy or secret material as the service group."""
    if not path.is_absolute() or path.is_symlink():
        raise ProtectedStagingError("protected immutable file rejected")
    resolved = path.resolve(strict=True)
    if (
        authority_root.resolve(strict=True)
        != service_root.resolve(strict=True) / "authority"
    ):
        raise ProtectedStagingError("protected authority root rejected")
    checkout_resolved = checkout.resolve(strict=True)
    metadata = metadata_reader(path)
    mode = stat.S_IMODE(metadata.st_mode)
    if (
        resolved == checkout_resolved
        or resolved.is_relative_to(checkout_resolved)
        or not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != authority.immutable_owner_uid
        or metadata.st_gid != authority.service_gid
        or mode != 0o440
        or metadata.st_size <= 0
        or metadata.st_size > maximum_bytes
    ):
        raise ProtectedStagingError("protected immutable file rejected")
    _validate_service_root_ancestry(
        authority,
        service_root=service_root,
        system_parent=system_parent,
        metadata_reader=metadata_reader,
    )
    _validate_controlled_ancestry(
        resolved, service_root, metadata_reader=metadata_reader
    )
    return path.read_bytes()


def validate_root_owned_service_directory(
    path: Path,
    checkout: Path,
    authority: ServiceIdentityAuthority,
    *,
    authority_root: Path = PROTECTED_AUTHORITY_ROOT,
    service_root: Path = PROTECTED_SERVICE_ROOT,
    system_parent: Path = PROTECTED_SYSTEM_PARENT,
    metadata_reader: MetadataReader = _lstat,
) -> Path:
    """Admit an immutable root-owned, service-readable directory."""
    if not path.is_absolute() or path.is_symlink() or not path.is_dir():
        raise ProtectedStagingError("protected immutable directory rejected")
    resolved = path.resolve(strict=True)
    if (
        authority_root.resolve(strict=True)
        != service_root.resolve(strict=True) / "authority"
    ):
        raise ProtectedStagingError("protected authority root rejected")
    checkout_resolved = checkout.resolve(strict=True)
    metadata = metadata_reader(path)
    if (
        resolved == checkout_resolved
        or resolved.is_relative_to(checkout_resolved)
        or metadata.st_uid != authority.immutable_owner_uid
        or metadata.st_gid != authority.service_gid
        or stat.S_IMODE(metadata.st_mode) not in {0o550, 0o750}
    ):
        raise ProtectedStagingError("protected immutable directory rejected")
    _validate_service_root_ancestry(
        authority,
        service_root=service_root,
        system_parent=system_parent,
        metadata_reader=metadata_reader,
    )
    _validate_controlled_ancestry(
        resolved, service_root, metadata_reader=metadata_reader
    )
    return resolved


def validate_service_owned_private_path(
    path: Path,
    checkout: Path,
    authority: ServiceIdentityAuthority,
    *,
    mutable_root: Path = PROTECTED_SERVICE_ROOT,
    mutable_class: Literal["builds", "state", "logs"] = "state",
    system_parent: Path = PROTECTED_SYSTEM_PARENT,
    metadata_reader: MetadataReader = _lstat,
) -> Path:
    """Admit the exact service-owned private mutable state boundary."""
    if not path.is_absolute() or path.is_symlink() or not path.is_dir():
        raise ProtectedStagingError("protected mutable directory rejected")
    resolved = path.resolve(strict=True)
    checkout_resolved = checkout.resolve(strict=True)
    metadata = metadata_reader(path)
    if (
        resolved == checkout_resolved
        or resolved.is_relative_to(checkout_resolved)
        or metadata.st_uid != authority.service_uid
        or metadata.st_gid != authority.service_gid
        or stat.S_IMODE(metadata.st_mode) != 0o700
        or resolved != mutable_root.resolve(strict=True) / mutable_class
    ):
        raise ProtectedStagingError("protected mutable directory rejected")
    _validate_service_root_ancestry(
        authority,
        service_root=mutable_root,
        system_parent=system_parent,
        metadata_reader=metadata_reader,
    )
    return resolved


def read_protected_file(
    path: Path,
    checkout: Path,
    *,
    owner_uid: int | None = None,
    maximum_bytes: int = MAX_PROTECTED_FILE_BYTES,
    require_nonempty: bool = True,
) -> bytes:
    """Read one private regular external file only after complete admission."""
    if not path.is_absolute() or path.is_symlink():
        raise ProtectedStagingError("protected file path rejected")
    resolved = path.resolve(strict=True)
    checkout_resolved = checkout.resolve(strict=True)
    metadata = path.stat(follow_symlinks=False)
    expected_uid = os.getuid() if owner_uid is None else owner_uid
    if (
        resolved == checkout_resolved
        or resolved.is_relative_to(checkout_resolved)
        or not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != expected_uid
        or stat.S_IMODE(metadata.st_mode) & 0o077
        or metadata.st_size > maximum_bytes
        or (require_nonempty and metadata.st_size == 0)
    ):
        raise ProtectedStagingError("protected file path rejected")
    return path.read_bytes()


def validate_protected_directory(
    path: Path, checkout: Path, *, owner_uid: int | None = None
) -> Path:
    """Admit one private external directory without symlink traversal."""
    if not path.is_absolute() or path.is_symlink() or not path.is_dir():
        raise ProtectedStagingError("protected directory rejected")
    resolved = path.resolve(strict=True)
    checkout_resolved = checkout.resolve(strict=True)
    metadata = path.stat(follow_symlinks=False)
    expected_uid = os.getuid() if owner_uid is None else owner_uid
    if (
        resolved == checkout_resolved
        or resolved.is_relative_to(checkout_resolved)
        or metadata.st_uid != expected_uid
        or stat.S_IMODE(metadata.st_mode) & 0o077
    ):
        raise ProtectedStagingError("protected directory rejected")
    return resolved


class ToolVersionRunner(Protocol):
    def __call__(self, executable: Path, arguments: Sequence[str]) -> str: ...


def validate_protected_executable(
    path: Path,
    checkout: Path,
    *,
    owner_uid: int | None = None,
    expected_version: str | None = None,
    version_runner: ToolVersionRunner | None = None,
) -> Path:
    """Admit an absolute private executable outside the checkout."""
    if not path.is_absolute() or path.is_symlink():
        raise ProtectedStagingError("protected executable rejected")
    resolved = path.resolve(strict=True)
    checkout_resolved = checkout.resolve(strict=True)
    metadata = path.stat(follow_symlinks=False)
    expected_uid = os.getuid() if owner_uid is None else owner_uid
    if (
        resolved == checkout_resolved
        or resolved.is_relative_to(checkout_resolved)
        or not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != expected_uid
        or stat.S_IMODE(metadata.st_mode) & 0o022
        or not metadata.st_mode & stat.S_IXUSR
    ):
        raise ProtectedStagingError("protected executable rejected")
    if expected_version is not None:
        if version_runner is None:
            raise ProtectedStagingError("protected executable version unavailable")
        observed = version_runner(resolved, ("version",))
        if observed != expected_version:
            raise ProtectedStagingError("protected executable version rejected")
    return resolved


def validate_root_owned_executable(
    path: Path,
    checkout: Path,
    authority: ServiceIdentityAuthority,
    tool: ExecutionToolAuthority,
    *,
    authority_root: Path = PROTECTED_AUTHORITY_ROOT,
    service_root: Path = PROTECTED_SERVICE_ROOT,
    system_parent: Path = PROTECTED_SYSTEM_PARENT,
    metadata_reader: MetadataReader = _lstat,
    observed_version: str | None = None,
) -> Path:
    """Admit one digest-bound root-owned protected or system executable."""
    if str(path) != tool.path or not path.is_absolute() or path.is_symlink():
        raise ProtectedStagingError("protected executable rejected")
    resolved = path.resolve(strict=True)
    checkout_resolved = checkout.resolve(strict=True)
    metadata = metadata_reader(path)
    mode = stat.S_IMODE(metadata.st_mode)
    if (
        resolved == checkout_resolved
        or resolved.is_relative_to(checkout_resolved)
        or not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != authority.immutable_owner_uid
        or mode & 0o022
        or not mode & 0o111
        or hashlib.sha256(path.read_bytes()).hexdigest() != tool.sha256
        or (observed_version is not None and observed_version != tool.version)
    ):
        raise ProtectedStagingError("protected executable rejected")
    if tool.system_protected:
        if metadata.st_gid != 0 or not str(resolved).startswith("/usr/bin/"):
            raise ProtectedStagingError("protected system executable rejected")
        _validate_controlled_ancestry(
            resolved.parent, Path("/usr"), metadata_reader=metadata_reader
        )
    else:
        if (
            metadata.st_gid != authority.service_gid
            or authority_root.resolve(strict=True)
            != service_root.resolve(strict=True) / "authority"
        ):
            raise ProtectedStagingError("protected executable rejected")
        _validate_service_root_ancestry(
            authority,
            service_root=service_root,
            system_parent=system_parent,
            metadata_reader=metadata_reader,
        )
        _validate_controlled_ancestry(
            resolved, service_root, metadata_reader=metadata_reader
        )
    return resolved


def terraform_version_runner(executable: Path, arguments: Sequence[str]) -> str:
    """Read exact Terraform version without inheriting caller environment."""
    del arguments
    result = subprocess.run(
        [str(executable), "version", "-json"],
        env={"PATH": str(executable.parent)},
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise ProtectedStagingError("protected Terraform version unavailable")
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        raise ProtectedStagingError("protected Terraform version unavailable") from None
    version = payload.get("terraform_version") if isinstance(payload, dict) else None
    if not isinstance(version, str):
        raise ProtectedStagingError("protected Terraform version unavailable")
    return version


def execution_tool_version_runner(executable: Path, tool: str) -> str:
    """Read a bounded normalized version from one admitted execution tool."""
    arguments = {
        "buildkite-agent": ("--version",),
        "openssl": ("version",),
        "ssh-keyscan": ("-V",),
        "ssh-keygen": ("-V",),
        "uv": ("--version",),
    }.get(tool)
    if arguments is None:
        raise ProtectedStagingError("protected executable version unavailable")
    version_executable = (
        Path("/usr/bin/ssh") if tool in {"ssh-keyscan", "ssh-keygen"} else executable
    )
    result = subprocess.run(
        [str(version_executable), *arguments],
        env={"PATH": str(version_executable.parent)},
        check=False,
        capture_output=True,
        text=True,
    )
    output = f"{result.stdout}\n{result.stderr}".strip()
    patterns = {
        "buildkite-agent": r"(?:version\s+)?([0-9]+(?:\.[0-9]+)+(?:\+[^\s]+)?)",
        "openssl": r"(?:OpenSSL|LibreSSL)\s+([^\s]+)",
        "ssh-keyscan": r"(OpenSSH_[^,\s]+)",
        "ssh-keygen": r"(OpenSSH_[^,\s]+)",
        "uv": r"uv\s+([^\s]+)",
    }
    match = re.search(patterns[tool], output)
    if result.returncode not in {0, 1} or match is None:
        raise ProtectedStagingError("protected executable version unavailable")
    return match.group(1)


def validate_macho_dependencies(
    dependency_map: Mapping[str, Sequence[str]],
    *,
    protected_native_files: Mapping[Path, str],
    digest_reader: Callable[[Path], str],
) -> None:
    """Reject native linkage outside Apple or exact protected dependency roots."""
    forbidden_prefixes = (
        "/Users/netdevops",
        "/opt/homebrew",
        "/private/tmp",
    )
    system_prefixes = ("/usr/lib/", "/System/Library/")
    for binary, dependencies in dependency_map.items():
        if not Path(binary).is_absolute():
            raise ProtectedStagingError("protected native dependency invalid")
        for value in dependencies:
            dependency = Path(value)
            if not dependency.is_absolute() or value.startswith(forbidden_prefixes):
                raise ProtectedStagingError("protected native dependency invalid")
            if value.startswith(system_prefixes):
                continue
            expected_digest = protected_native_files.get(dependency)
            if expected_digest is None or digest_reader(dependency) != expected_digest:
                raise ProtectedStagingError("protected native dependency invalid")


def inspect_native_dependencies(root: Path) -> dict[str, tuple[str, ...]]:
    """Read every Mach-O dependency below one admitted authority root."""
    observed: dict[str, tuple[str, ...]] = {}
    paths = (root,) if root.is_file() else tuple(root.rglob("*"))
    for path in sorted(value for value in paths if value.is_file()):
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
        observed[str(path)] = tuple(
            line.strip().split(" ", 1)[0]
            for line in linked.stdout.splitlines()[1:]
            if line.strip()
        )
    return observed


def inspect_runtime_native_dependencies(runtime: Path) -> dict[str, tuple[str, ...]]:
    """Compatibility wrapper for inspecting the isolated runtime."""
    return inspect_native_dependencies(runtime)


def inspect_combined_native_dependency_graph(
    scopes: Mapping[str, Path],
    *,
    inspector: Callable[[Path], Mapping[str, Sequence[str]]] = (
        inspect_native_dependencies
    ),
) -> dict[str, dict[str, tuple[str, ...]]]:
    """Inspect one canonical, scope-qualified native authority graph."""
    if not scopes or any(not name or "/" in name for name in scopes):
        raise ProtectedStagingError("protected native dependency scope rejected")
    return {
        scope: {
            binary: tuple(dependencies)
            for binary, dependencies in sorted(inspector(path).items())
        }
        for scope, path in sorted(scopes.items())
    }


def native_dependency_graph_sha256(
    graph: Mapping[str, Mapping[str, Sequence[str]]],
) -> str:
    """Digest the canonical graph with scope and full path identity."""
    canonical = {
        scope: {
            binary: tuple(dependencies)
            for binary, dependencies in sorted(dependency_map.items())
        }
        for scope, dependency_map in sorted(graph.items())
    }
    return hashlib.sha256(
        json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def validate_combined_native_dependency_graph(
    graph: Mapping[str, Mapping[str, Sequence[str]]],
    *,
    protected_native_files: Mapping[Path, str],
    digest_reader: Callable[[Path], str],
) -> None:
    """Admit every edge, including edges from protected dependencies themselves."""
    if not graph:
        raise ProtectedStagingError("protected native dependency graph rejected")
    for dependency_map in graph.values():
        validate_macho_dependencies(
            dependency_map,
            protected_native_files=protected_native_files,
            digest_reader=digest_reader,
        )


def directory_inventory_sha256(root: Path) -> str:
    """Digest exact relative names, file digests, modes and symlink denial."""
    entries: dict[str, dict[str, object]] = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ProtectedStagingError("protected directory inventory rejected")
        relative = str(path.relative_to(root))
        if path.is_file():
            entries[relative] = {
                "type": "file",
                "mode": stat.S_IMODE(path.stat().st_mode),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
        elif path.is_dir():
            entries[relative] = {
                "type": "directory",
                "mode": stat.S_IMODE(path.stat().st_mode),
            }
    return hashlib.sha256(
        json.dumps(entries, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def validate_root_owned_immutable_tree(
    root: Path,
    checkout: Path,
    authority: ServiceIdentityAuthority,
    expected_inventory_sha256: str,
    *,
    expected_collections: Mapping[str, str] | None = None,
    authority_root: Path = PROTECTED_AUTHORITY_ROOT,
    service_root: Path = PROTECTED_SERVICE_ROOT,
    system_parent: Path = PROTECTED_SYSTEM_PARENT,
    metadata_reader: MetadataReader = _lstat,
) -> None:
    """Re-admit every object in a root-owned immutable authority tree."""
    validate_root_owned_service_directory(
        root,
        checkout,
        authority,
        authority_root=authority_root,
        service_root=service_root,
        system_parent=system_parent,
        metadata_reader=metadata_reader,
    )
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ProtectedStagingError("protected immutable tree rejected")
        metadata = metadata_reader(path)
        mode = stat.S_IMODE(metadata.st_mode)
        if (
            metadata.st_uid != authority.immutable_owner_uid
            or metadata.st_gid != authority.service_gid
            or mode & 0o022
            or not (stat.S_ISREG(metadata.st_mode) or stat.S_ISDIR(metadata.st_mode))
        ):
            raise ProtectedStagingError("protected immutable tree rejected")
    if directory_inventory_sha256(root) != expected_inventory_sha256:
        raise ProtectedStagingError("protected immutable tree inventory rejected")
    if expected_collections is not None:
        actual: dict[str, str] = {}
        for name in expected_collections:
            namespace, collection = name.split(".", 1)
            metadata_path = (
                root / "ansible_collections" / namespace / collection / "MANIFEST.json"
            )
            try:
                payload = json.loads(metadata_path.read_text(encoding="utf-8"))
                info = payload["collection_info"]
                actual[name] = info["version"]
            except (OSError, KeyError, TypeError, json.JSONDecodeError):
                raise ProtectedStagingError(
                    "protected Ansible collection metadata rejected"
                ) from None
        if actual != dict(expected_collections):
            raise ProtectedStagingError("protected Ansible collection version rejected")


def validate_system_rooted_directory(
    path: Path,
    checkout: Path,
    *,
    metadata_reader: MetadataReader = _lstat,
) -> Path:
    """Admit a root-owned system directory with non-writable ancestry."""
    if not path.is_absolute() or path.is_symlink() or not path.is_dir():
        raise ProtectedStagingError("protected system directory rejected")
    resolved = path.resolve(strict=True)
    checkout_resolved = checkout.resolve(strict=True)
    if resolved == checkout_resolved or resolved.is_relative_to(checkout_resolved):
        raise ProtectedStagingError("protected system directory rejected")
    current = resolved
    while current != Path("/"):
        metadata = metadata_reader(current)
        if metadata.st_uid != 0 or stat.S_IMODE(metadata.st_mode) & 0o022:
            raise ProtectedStagingError("protected system directory rejected")
        current = current.parent
    return resolved


def validate_native_runtime_authority(
    manifest: ProtectedStagingManifest,
    runtime_root: Path,
    checkout: Path,
    *,
    dependency_inspector: Callable[
        [Mapping[str, Path]], Mapping[str, Mapping[str, Sequence[str]]]
    ],
    authority_root: Path = PROTECTED_AUTHORITY_ROOT,
    service_root: Path = PROTECTED_SERVICE_ROOT,
    system_parent: Path = PROTECTED_SYSTEM_PARENT,
    metadata_reader: MetadataReader = _lstat,
) -> None:
    """Re-admit native trees, files and fresh Mach-O linkage at startup."""
    native_root = authority_root / "native"
    admitted_roots: list[Path] = []
    for dependency in manifest.native_dependencies:
        root = Path(dependency.root)
        if root.parent != native_root or root.name != dependency.name:
            raise ProtectedStagingError("protected native dependency root rejected")
        validate_root_owned_immutable_tree(
            root,
            checkout,
            manifest.service_identity,
            dependency.inventory_sha256,
            authority_root=authority_root,
            service_root=service_root,
            system_parent=system_parent,
            metadata_reader=metadata_reader,
        )
        version_file = root / "VERSION"
        try:
            observed_version = version_file.read_text(encoding="utf-8").strip()
        except OSError:
            raise ProtectedStagingError(
                "protected native dependency version rejected"
            ) from None
        if observed_version != dependency.version:
            raise ProtectedStagingError("protected native dependency version rejected")
        admitted_roots.append(root.resolve(strict=True))
    protected_files: dict[Path, str] = {}
    for value, digest in manifest.protected_native_files.items():
        path = Path(value)
        resolved = path.resolve(strict=True)
        if not any(resolved.is_relative_to(root) for root in admitted_roots):
            raise ProtectedStagingError("protected native file root rejected")
        metadata = metadata_reader(path)
        if (
            path.is_symlink()
            or not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != 0
            or metadata.st_gid != manifest.service_identity.service_gid
            or stat.S_IMODE(metadata.st_mode) & 0o022
            or hashlib.sha256(path.read_bytes()).hexdigest() != digest
        ):
            raise ProtectedStagingError("protected native file rejected")
        protected_files[resolved] = digest
    scopes = {
        "runtime": runtime_root,
        "python": Path(manifest.python_interpreter_path),
        "openssl-tool": Path(manifest.openssl.path),
        "terraform": Path(manifest.terraform.path),
        "buildkite-agent": Path(manifest.buildkite_agent.path),
        "uv-install-time": Path(manifest.uv.path),
        **{
            dependency.name: Path(dependency.root)
            for dependency in manifest.native_dependencies
        },
    }
    graph = dict(dependency_inspector(scopes))
    if set(graph) != set(scopes):
        raise ProtectedStagingError("protected native dependency scope changed")
    validate_combined_native_dependency_graph(
        graph,
        protected_native_files=protected_files,
        digest_reader=lambda path: hashlib.sha256(path.read_bytes()).hexdigest(),
    )
    admission = native_dependency_graph_sha256(graph)
    if admission != manifest.native_dependency_admission_sha256:
        raise ProtectedStagingError("protected native dependency admission changed")


def build_protected_terraform_environment(
    *,
    terraform_data_dir: Path,
    cml_address: str,
    cml_token: str,
    cml_ca_pem: str,
    variables: Mapping[str, str],
    trusted_path: str,
) -> dict[str, str]:
    """Construct, rather than inherit, the complete Terraform environment."""
    expected_variables = {
        "TF_VAR_staging_run_id",
        "TF_VAR_lifecycle_state",
        "TF_VAR_cisco_bootstrap_hostname",
        "TF_VAR_cisco_bootstrap_management_cidr",
        "TF_VAR_cisco_bootstrap_username",
        "TF_VAR_cisco_bootstrap_password",
        "TF_VAR_junos_bootstrap_hostname",
        "TF_VAR_junos_bootstrap_management_cidr",
        "TF_VAR_junos_bootstrap_username",
        "TF_VAR_junos_bootstrap_password_hash",
    }
    if set(variables) != expected_variables or not all(variables.values()):
        raise ProtectedStagingError("protected Terraform variables rejected")
    return {
        "PATH": trusted_path,
        "TF_IN_AUTOMATION": "1",
        "TF_DATA_DIR": str(terraform_data_dir),
        "CML2_ADDRESS": cml_address,
        "CML2_TOKEN": cml_token,
        "CML2_CACERT": cml_ca_pem,
        **dict(variables),
    }


def derive_run_directory(state_root: Path, build_id: UUID) -> tuple[str, Path]:
    """Derive the sole normal-run directory from immutable Buildkite identity."""
    run_id = f"bk-{build_id}"
    ephemeral = state_root / "ephemeral"
    if ephemeral.is_symlink():
        raise ProtectedStagingError("protected run parent rejected")
    ephemeral.mkdir(mode=0o700, exist_ok=True)
    if stat.S_IMODE(ephemeral.stat().st_mode) & 0o077:
        raise ProtectedStagingError("protected run parent rejected")
    run_directory = ephemeral / run_id
    if run_directory.exists() or run_directory.is_symlink():
        raise ProtectedStagingError("protected retained run requires recovery")
    run_directory.mkdir(mode=0o700)
    return run_id, run_directory


class ProtectedStaticInventory:
    """Exact immutable staging inventory for read-only planning only."""

    def __init__(self, targets: Sequence[ProtectedStagingTarget]) -> None:
        devices = {}
        for target in targets:
            port = 22 if target.device_id == 6 else 830
            devices[target.name] = InventoryDevice(
                name=target.name,
                host=target.host,
                port=port,
                platform=target.platform,
                expected_hostname=target.name,
                inventory_source="netbox",
                inventory_object_id=f"netbox:dcim.device:{target.device_id}",
                inventory_interface_object_id=(
                    f"netbox:dcim.interface:{target.interface_id}"
                ),
            )
        if set(devices) != {"stg-core-02", "stg-edge-junos-01"}:
            raise ProtectedStagingError("protected static inventory rejected")
        self._devices = devices

    def resolve(self, name: str, interface: str | None = None) -> InventoryDevice:
        try:
            device = self._devices[name]
        except KeyError:
            raise ProtectedStagingError("protected static target rejected") from None
        expected_interface = {
            "stg-core-02": "GigabitEthernet2",
            "stg-edge-junos-01": "ge-0/0/2",
        }[name]
        if interface is None:
            return device
        if interface != expected_interface:
            raise ProtectedStagingError("protected static interface rejected")
        device_id = device.inventory_object_id.rsplit(":", 1)[-1]
        return device.model_copy(
            update={
                "inventory_interface_object_id": (
                    f"protected:cml.integration:{device_id}:{interface}"
                )
            }
        )


class CachedProtectedSecrets:
    """Expose only already admitted in-memory credentials to planning."""

    def __init__(
        self,
        devices: Mapping[str, InventoryDevice],
        credentials: Mapping[str, DeviceCredentials],
    ) -> None:
        if set(devices) != set(credentials) or set(devices) != {
            "stg-core-02",
            "stg-edge-junos-01",
        }:
            raise ProtectedStagingError("protected cached secrets rejected")
        self._devices = dict(devices)
        self._credentials = dict(credentials)

    def reference(self, device: InventoryDevice) -> CredentialReference:
        accepted = self._devices.get(device.name)
        if accepted != device:
            raise ProtectedStagingError("protected cached target rejected")
        device_id = device.inventory_object_id.rsplit(":", 1)[-1]
        return CredentialReference(
            "openbao", f"openbao:kv-v2:ncdp/devices/{device_id}/ssh"
        )

    def load(self, device: InventoryDevice) -> DeviceCredentials:
        self.reference(device)
        return self._credentials[device.name]


class ProtectedCommandRunner:
    """Run one admitted executable without inheriting the caller environment."""

    def __call__(
        self,
        arguments: Sequence[str],
        *,
        input_text: str | None = None,
    ) -> str:
        if not arguments or not Path(arguments[0]).is_absolute():
            raise ProtectedStagingError("protected command rejected")
        result = subprocess.run(
            list(arguments),
            input=input_text,
            env={"PATH": str(Path(arguments[0]).parent)},
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise ProtectedStagingError("protected command failed")
        return result.stdout


def load_protected_staging_credentials(
    jwt: BuildkiteOIDCJWT,
    context: BuildkiteStagingContext,
    manifest: ProtectedStagingManifest,
    targets: Sequence[ProtectedStagingTarget],
    *,
    transport=None,
) -> dict[str, DeviceCredentials]:
    """Load exactly devices 6/7 through their one-policy workload identities."""
    provider = BuildkiteStagingSecretProvider(
        jwt, context, url=manifest.openbao_url, transport=transport
    )
    inventory = ProtectedStaticInventory(targets)
    credentials: dict[str, DeviceCredentials] = {}
    for target in targets:
        ProtectedStagingSecretAuthority.validate_target(target)
        device = inventory.resolve(target.name)
        credentials[target.name] = provider.load(device)
    if set(credentials) != {"stg-core-02", "stg-edge-junos-01"}:
        raise ProtectedStagingError("protected credential population rejected")
    return credentials


def derive_junos_password_verifier(
    executable: Path,
    password: str,
    runner: ProtectedCommandRunner,
) -> str:
    """Derive the fixed-salt SHA-512 verifier without placing a secret in argv."""
    output = runner(
        (
            str(executable),
            "passwd",
            "-6",
            "-salt",
            "ncdpedgejunos01",
            "-stdin",
        ),
        input_text=password,
    ).strip()
    import re

    if not re.fullmatch(r"\$6\$ncdpedgejunos01\$[A-Za-z0-9./]{86}", output):
        raise ProtectedStagingError("protected Junos verifier derivation failed")
    return output


class ProtectedReadinessProbe:
    """Bound TCP readiness to the exact staging management services."""

    def __init__(
        self,
        connector=socket.create_connection,
        monotonic=time.monotonic,
        sleeper=time.sleep,
    ) -> None:
        self._connector = connector
        self._monotonic = monotonic
        self._sleeper = sleeper

    def wait(
        self, targets: Sequence[ProtectedStagingTarget], timeout: int = 1200
    ) -> dict[str, float]:
        expected = {6: ("192.168.4.30", (22,)), 7: ("192.168.4.31", (22, 830))}
        results: dict[str, float] = {}
        for target in targets:
            authority = expected.get(target.device_id)
            if authority is None or target.host != authority[0]:
                raise ProtectedOperationError(FailureCode.READINESS)
            started = self._monotonic()
            while self._monotonic() - started < timeout:
                try:
                    for port in authority[1]:
                        connection = self._connector((target.host, port), timeout=2)
                        connection.close()
                except OSError:
                    self._sleeper(10)
                    continue
                results[target.name] = round(self._monotonic() - started, 1)
                break
            else:
                raise ProtectedOperationError(FailureCode.READINESS)
        return results


class ProtectedSSHHostTrust:
    """Create one run-scoped stable known-hosts file with admitted executables."""

    def __init__(self, keyscan: Path, keygen: Path) -> None:
        self._keyscan = keyscan
        self._keygen = keygen

    @staticmethod
    def _keys(value: str) -> frozenset[tuple[str, str]]:
        keys: set[tuple[str, str]] = set()
        for line in value.splitlines():
            fields = line.split()
            if line.startswith("#") or len(fields) < 3:
                continue
            keys.add((fields[1], fields[2]))
        return frozenset(keys)

    def establish(
        self,
        targets: Sequence[ProtectedStagingTarget],
        run_directory: Path,
        *,
        attempts: int = 12,
    ) -> Path:
        known_hosts_directory = run_directory / ".ssh"
        known_hosts_directory.mkdir(mode=0o700)
        known_hosts = known_hosts_directory / "known_hosts"
        descriptor = os.open(known_hosts, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(descriptor)
        expected = {6: ("192.168.4.30", (22,)), 7: ("192.168.4.31", (22, 830))}
        for target in targets:
            host, ports = expected.get(target.device_id, ("", ()))
            if host != target.host:
                raise ProtectedOperationError(FailureCode.HOST_TRUST)
            for port in ports:
                query = host if port == 22 else f"[{host}]:{port}"
                subprocess.run(
                    [str(self._keygen), "-R", query, "-f", str(known_hosts)],
                    env={"PATH": str(self._keygen.parent)},
                    check=False,
                    capture_output=True,
                    text=True,
                )
                previous: frozenset[tuple[str, str]] | None = None
                stable = 0
                accepted = ""
                for _attempt in range(attempts):
                    result = subprocess.run(
                        [str(self._keyscan), "-H", "-p", str(port), host],
                        env={"PATH": str(self._keyscan.parent)},
                        check=False,
                        capture_output=True,
                        text=True,
                    )
                    keys = (
                        self._keys(result.stdout)
                        if result.returncode == 0
                        else frozenset()
                    )
                    if keys:
                        stable = stable + 1 if keys == previous else 1
                        previous = keys
                        accepted = result.stdout
                        if stable == 3:
                            break
                    time.sleep(5)
                if stable != 3:
                    raise ProtectedOperationError(FailureCode.HOST_TRUST)
                with known_hosts.open("a", encoding="utf-8") as stream:
                    stream.write(accepted)
        known_hosts.chmod(0o600)
        return known_hosts


class ProtectedNCDPReadOnlyValidator:
    """Run only the installed NCDP planning path against the exact staging pair."""

    def __init__(
        self,
        bundle_root: Path,
        ssh_keygen: Path,
        ansible_collections_root: Path,
        *,
        sleeper=time.sleep,
    ) -> None:
        self._bundle_root = bundle_root
        self._ssh_keygen = ssh_keygen
        self._ansible_collections_root = ansible_collections_root
        self._sleeper = sleeper

    def __call__(
        self,
        targets: Sequence[ProtectedStagingTarget],
        credentials: Mapping[str, DeviceCredentials],
        known_hosts: Path,
    ) -> dict[str, int]:
        ansible_environment = {
            "ANSIBLE_COLLECTIONS_PATH": str(self._ansible_collections_root)
        }
        verify_deployment_ansible_runtime(
            self._bundle_root, environment=ansible_environment
        )
        inventory = ProtectedStaticInventory(targets)
        devices = {target.name: inventory.resolve(target.name) for target in targets}
        secrets = CachedProtectedSecrets(devices, credentials)
        adapters = {
            "stg-core-02": (
                "GigabitEthernet2",
                AnsibleRunnerCiscoAdapter(
                    self._bundle_root,
                    known_hosts=known_hosts,
                    ssh_keygen=self._ssh_keygen,
                    collections_path=self._ansible_collections_root,
                ),
            ),
            "stg-edge-junos-01": (
                "ge-0/0/2",
                JunosPyEZAdapter(known_hosts=known_hosts, ssh_keygen=self._ssh_keygen),
            ),
        }
        attempts_by_device: dict[str, int] = {}
        for name, (interface, adapter) in adapters.items():
            intent = InterfaceDescriptionIntent(
                change_id=f"protected-staging-{name}-readonly",
                kind="interface_description",
                target=name,
                interface=interface,
                desired=DesiredDescription(
                    description="NCDP ephemeral staging validation"
                ),
            )
            attempts = 0
            while attempts < 13:
                attempts += 1
                try:
                    plan_change(intent, inventory, secrets, adapter)
                    attempts_by_device[name] = attempts
                    break
                except ProviderReadinessError:
                    if attempts == 13:
                        raise ProtectedOperationError(FailureCode.VALIDATION) from None
                    self._sleeper(15)
        return attempts_by_device


class ProtectedRecoveryMetadata(BaseModel):
    """Non-secret exact retained-run authority paired with Terraform state."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    schema_version: Literal[1] = 1
    run_id: str
    build_id: UUID
    source_commit: str
    manifest_digest: str
    bundle_digest: str
    lab_id: UUID | None = None
    lab_title: str
    terraform_addresses: tuple[str, ...]

    @model_validator(mode="after")
    def exact_metadata(self) -> ProtectedRecoveryMetadata:
        if (
            self.run_id != f"bk-{self.build_id}"
            or self.lab_title != f"NCDP Staging {self.run_id}"
            or (self.lab_id is not None and str(self.lab_id) == BROWNFIELD_LAB_UUID)
            or set(self.terraform_addresses) != EXPECTED_TERRAFORM_ADDRESSES
            or len(self.terraform_addresses) != len(EXPECTED_TERRAFORM_ADDRESSES)
        ):
            raise ValueError("protected recovery metadata rejected")
        return self


def write_recovery_metadata(path: Path, metadata: ProtectedRecoveryMetadata) -> None:
    """Create one private recovery record without overwrite."""
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        stream.write(metadata.model_dump_json(indent=2) + "\n")


def replace_recovery_metadata(path: Path, metadata: ProtectedRecoveryMetadata) -> None:
    """Atomically add the admitted disposable UUID to an exact provisional record."""
    temporary = path.with_suffix(".tmp")
    descriptor = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(metadata.model_dump_json(indent=2) + "\n")
        temporary.replace(path)
    finally:
        if temporary.exists():
            temporary.unlink()


def load_recovery_metadata(
    path: Path,
    checkout: Path,
    manifest: ProtectedStagingManifest,
) -> ProtectedRecoveryMetadata:
    """Load retained authority and bind it to the exact installed version."""
    try:
        metadata = ProtectedRecoveryMetadata.model_validate_json(
            read_protected_file(path, checkout).decode()
        )
    except (UnicodeDecodeError, ValueError):
        raise ProtectedStagingError("protected recovery metadata invalid") from None
    if (
        metadata.source_commit != manifest.source_commit
        or metadata.manifest_digest != manifest.digest
        or metadata.bundle_digest != manifest.bundle_digest
    ):
        raise ProtectedStagingError("protected recovery version mismatch")
    return metadata


class ProtectedRuntimeEvidence(BaseModel):
    """Allowlisted result of one complete protected staging lifecycle."""

    model_config = ConfigDict(frozen=False, extra="forbid")
    schema_version: Literal[2] = 2
    pipeline_id: UUID
    build_id: UUID
    job_id: UUID
    source_commit: str
    protected_bundle_digest: str
    manifest_digest: str
    run_id: str
    staging_device_ids: tuple[Literal[6], Literal[7]] = (6, 7)
    homolog_ids: tuple[Literal[1], Literal[2]] = (1, 2)
    management_cidrs: tuple[str, str] = (
        "192.168.4.30/24",
        "192.168.4.31/24",
    )
    credential_references: tuple[str, str] = (
        "openbao:kv-v2:ncdp/devices/6/ssh",
        "openbao:kv-v2:ncdp/devices/7/ssh",
    )
    lab_id: UUID | None = None
    node_ids: dict[str, UUID] = Field(default_factory=dict)
    link_ids: dict[str, UUID] = Field(default_factory=dict)
    terraform_actions: dict[str, int] = Field(default_factory=dict)
    readiness_seconds: dict[str, float] = Field(default_factory=dict)
    validation_attempts: dict[str, int] = Field(default_factory=dict)
    creation_result: Literal["not_attempted", "passed", "failed"] = "not_attempted"
    readiness_result: Literal["not_attempted", "passed", "failed"] = "not_attempted"
    validation_result: Literal["not_attempted", "passed", "failed"] = "not_attempted"
    cleanup_result: Literal["not_attempted", "passed", "failed", "retained"] = (
        "not_attempted"
    )
    absence_result: Literal["not_attempted", "passed", "failed"] = "not_attempted"
    state_retirement_result: Literal["not_attempted", "passed", "failed"] = (
        "not_attempted"
    )
    primary_failure: FailureCode | None = None
    cleanup_failure: FailureCode | None = None
    overall_result: Literal["running", "passed", "failed"] = "running"

    def safe_json(self) -> str:
        return self.model_dump_json(exclude_none=True)


class ProtectedLifecycleOperations(Protocol):
    """Privileged ports composed only inside the installed runtime."""

    def admit(self) -> None: ...
    def create(self) -> ProtectedTerraformOutputs: ...
    def verify_realization(self, outputs: ProtectedTerraformOutputs) -> None: ...
    def start(self) -> None: ...
    def readiness(self) -> dict[str, float]: ...
    def establish_host_trust(self) -> None: ...
    def validate_read_only(self) -> dict[str, int]: ...
    def state_addresses(self) -> set[str]: ...
    def cleanup_retained(self) -> bool: ...
    def prove_absent(self, lab_id: UUID, lab_title: str) -> None: ...
    def prove_title_absent(self, lab_title: str) -> None: ...


class ReadOnlyValidationPort(Protocol):
    def __call__(
        self,
        targets: Sequence[ProtectedStagingTarget],
        credentials: Mapping[str, DeviceCredentials],
        known_hosts: Path,
    ) -> dict[str, int]: ...


class ProtectedRuntimeOperations:
    """Concrete orchestration of the admitted protected integration adapters."""

    def __init__(
        self,
        *,
        manifest: ProtectedStagingManifest,
        run_id: str,
        run_directory: Path,
        resolver: ProtectedStagingInventoryResolver,
        cml: ProtectedCMLClient,
        terraform: ProtectedTerraformExecutor,
        credentials: Mapping[str, DeviceCredentials],
        readiness: ProtectedReadinessProbe,
        host_trust: ProtectedSSHHostTrust,
        validator: ReadOnlyValidationPort,
    ) -> None:
        self._manifest = manifest
        self._run_id = run_id
        self._run_directory = run_directory
        self._resolver = resolver
        self._cml = cml
        self._terraform = terraform
        self._credentials = dict(credentials)
        self._readiness = readiness
        self._host_trust = host_trust
        self._validator = validator
        self._targets: tuple[ProtectedStagingTarget, ...] = ()
        self._known_hosts: Path | None = None

    def admit(self) -> None:
        try:
            self._targets = self._resolver.resolve()
        except InventoryError:
            raise ProtectedOperationError(FailureCode.INVENTORY_AUTHORITY) from None
        if set(self._credentials) != {target.name for target in self._targets}:
            raise ProtectedOperationError(FailureCode.CREDENTIAL_AUTHORITY)
        try:
            admit_cml_labs(self._manifest, self._run_id, self._cml.labs())
        except ProtectedStagingError:
            raise ProtectedOperationError(FailureCode.CML_ADMISSION) from None
        try:
            self._terraform.initialize()
        except ProtectedStagingError:
            raise ProtectedOperationError(FailureCode.TERRAFORM_INIT) from None

    def create(self) -> ProtectedTerraformOutputs:
        try:
            metadata_path = self._run_directory / "recovery-metadata.json"
            provisional = ProtectedRecoveryMetadata(
                run_id=self._run_id,
                build_id=UUID(self._run_id.removeprefix("bk-")),
                source_commit=self._manifest.source_commit,
                manifest_digest=self._manifest.digest,
                bundle_digest=self._manifest.bundle_digest,
                lab_title=f"NCDP Staging {self._run_id}",
                terraform_addresses=tuple(sorted(EXPECTED_TERRAFORM_ADDRESSES)),
            )
            write_recovery_metadata(metadata_path, provisional)
            self._terraform.execute("create")
            outputs = self._terraform.outputs(self._run_id)
            metadata = ProtectedRecoveryMetadata(
                run_id=self._run_id,
                build_id=UUID(self._run_id.removeprefix("bk-")),
                source_commit=self._manifest.source_commit,
                manifest_digest=self._manifest.digest,
                bundle_digest=self._manifest.bundle_digest,
                lab_id=outputs.lab_id,
                lab_title=outputs.lab_title,
                terraform_addresses=tuple(sorted(EXPECTED_TERRAFORM_ADDRESSES)),
            )
            replace_recovery_metadata(metadata_path, metadata)
            return outputs
        except (ValueError, ProtectedStagingError):
            raise ProtectedOperationError(FailureCode.TERRAFORM_CREATE) from None

    def verify_realization(self, outputs: ProtectedTerraformOutputs) -> None:
        try:
            labs = {observation.lab_id: observation for observation in self._cml.labs()}
            observed = labs.get(str(outputs.lab_id))
            if observed is None or observed.title != outputs.lab_title:
                raise ProtectedStagingError("protected realization missing")
            nodes, links = self._cml.lab_structure(outputs.lab_id)
            if set(nodes) != {str(value) for value in outputs.node_ids.values()}:
                raise ProtectedStagingError("protected realization nodes changed")
            if set(links) != {str(value) for value in outputs.link_ids.values()}:
                raise ProtectedStagingError("protected realization links changed")
            expected = {
                str(outputs.node_ids["system_bridge"]): (
                    "system-bridge",
                    "external_connector",
                    None,
                ),
                str(outputs.node_ids["management_switch"]): (
                    "management-switch",
                    "unmanaged_switch",
                    None,
                ),
                str(outputs.node_ids["cisco"]): (
                    "stg-core-02",
                    "cat8000v",
                    self._manifest.cml.cat8000v_image,
                ),
                str(outputs.node_ids["junos"]): (
                    "stg-edge-junos-01",
                    "vjunos-router",
                    self._manifest.cml.vjunos_image,
                ),
            }
            for node_id, (label, definition, image) in expected.items():
                node = nodes[node_id]
                if (
                    node.get("id") not in (None, node_id)
                    or node.get("label") != label
                    or node.get("node_definition") != definition
                    or (image is not None and node.get("image_definition") != image)
                    or node.get("state") != "DEFINED_ON_CORE"
                ):
                    raise ProtectedStagingError("protected realization changed")
        except ProtectedStagingError:
            raise ProtectedOperationError(FailureCode.REALIZATION) from None

    def start(self) -> None:
        try:
            self._terraform.set_lifecycle_state("STARTED")
            self._terraform.execute("start")
        except ProtectedStagingError:
            raise ProtectedOperationError(FailureCode.TERRAFORM_START) from None

    def readiness(self) -> dict[str, float]:
        return self._readiness.wait(self._targets)

    def establish_host_trust(self) -> None:
        self._known_hosts = self._host_trust.establish(
            self._targets, self._run_directory
        )

    def validate_read_only(self) -> dict[str, int]:
        if self._known_hosts is None:
            raise ProtectedOperationError(FailureCode.HOST_TRUST)
        fresh = self._resolver.resolve()
        if fresh != self._targets:
            raise ProtectedOperationError(FailureCode.INVENTORY_AUTHORITY)
        try:
            return self._validator(fresh, self._credentials, self._known_hosts)
        except ProtectedStagingError:
            raise
        except Exception:
            raise ProtectedOperationError(FailureCode.VALIDATION) from None

    def state_addresses(self) -> set[str]:
        return self._terraform.state_addresses()

    def cleanup_retained(self) -> bool:
        return self._terraform.cleanup_retained()

    def prove_absent(self, lab_id: UUID, lab_title: str) -> None:
        labs = self._cml.labs()
        if any(
            observation.lab_id == str(lab_id) or observation.title == lab_title
            for observation in labs
        ):
            raise ProtectedStagingError("protected CML absence proof failed")

    def prove_title_absent(self, lab_title: str) -> None:
        if any(item.title == lab_title for item in self._cml.labs()):
            raise ProtectedStagingError("protected CML absence proof failed")


class ProtectedRecoveryOperations:
    """Exact retained-state cleanup ports; deliberately has no create/start API."""

    def __init__(
        self, cml: ProtectedCMLClient, terraform: ProtectedTerraformExecutor
    ) -> None:
        self._cml = cml
        self._terraform = terraform

    def state_addresses(self) -> set[str]:
        return self._terraform.state_addresses()

    def cleanup_retained(self) -> bool:
        return self._terraform.cleanup_retained()

    def prove_absent(self, lab_id: UUID, lab_title: str) -> None:
        if any(
            item.lab_id == str(lab_id) or item.title == lab_title
            for item in self._cml.labs()
        ):
            raise ProtectedStagingError("protected recovery absence proof failed")

    def prove_title_absent(self, lab_title: str) -> None:
        if any(item.title == lab_title for item in self._cml.labs()):
            raise ProtectedStagingError("protected recovery absence proof failed")


@dataclass(frozen=True)
class LifecycleIdentity:
    pipeline_id: UUID
    build_id: UUID
    job_id: UUID
    source_commit: str
    bundle_digest: str
    manifest_digest: str


def run_protected_lifecycle(
    identity: LifecycleIdentity,
    run_directory: Path,
    operations: ProtectedLifecycleOperations,
) -> ProtectedRuntimeEvidence:
    """Run once, then authorize cleanup only from exact structural state."""
    run_id = f"bk-{identity.build_id}"
    evidence = ProtectedRuntimeEvidence(
        pipeline_id=identity.pipeline_id,
        build_id=identity.build_id,
        job_id=identity.job_id,
        source_commit=identity.source_commit,
        protected_bundle_digest=identity.bundle_digest,
        manifest_digest=identity.manifest_digest,
        run_id=run_id,
    )
    outputs: ProtectedTerraformOutputs | None = None
    create_attempted = False
    try:
        operations.admit()
        evidence.creation_result = "failed"
        create_attempted = True
        outputs = operations.create()
        evidence.creation_result = "passed"
        evidence.terraform_actions["create"] = 10
        evidence.lab_id = outputs.lab_id
        evidence.node_ids = outputs.node_ids
        evidence.link_ids = outputs.link_ids
        operations.verify_realization(outputs)
        operations.start()
        evidence.terraform_actions["start"] = 1
        evidence.readiness_seconds = operations.readiness()
        evidence.readiness_result = "passed"
        operations.establish_host_trust()
        evidence.validation_attempts = operations.validate_read_only()
        evidence.validation_result = "passed"
    except ProtectedOperationError as error:
        evidence.primary_failure = error.code
    except ProtectedStagingError:
        evidence.primary_failure = (
            FailureCode.LOCAL_AUTHORITY
            if evidence.creation_result == "not_attempted"
            else FailureCode.TERRAFORM_CREATE
            if outputs is None
            else FailureCode.VALIDATION
            if evidence.readiness_result == "passed"
            else FailureCode.READINESS
        )
    finally:
        try:
            state = operations.state_addresses()
            if not create_attempted:
                if state:
                    evidence.cleanup_result = "retained"
                    evidence.cleanup_failure = FailureCode.CLEANUP_UNAUTHORIZED
                else:
                    evidence.cleanup_result = "passed"
            elif state:
                if not state.issubset(EXPECTED_TERRAFORM_ADDRESSES):
                    evidence.cleanup_result = "retained"
                    evidence.cleanup_failure = FailureCode.CLEANUP_UNAUTHORIZED
                else:
                    operations.cleanup_retained()
                    evidence.terraform_actions["destroy"] = len(state)
                    evidence.cleanup_result = "passed"
            else:
                evidence.cleanup_result = "passed"
        except ProtectedStagingError:
            if evidence.cleanup_result != "retained":
                evidence.cleanup_result = "failed"
                evidence.cleanup_failure = FailureCode.CLEANUP_FAILED
        if create_attempted and evidence.cleanup_result == "passed":
            try:
                if operations.state_addresses():
                    raise ProtectedStagingError("protected state remains")
                if outputs is None:
                    operations.prove_title_absent(f"NCDP Staging {run_id}")
                else:
                    operations.prove_absent(outputs.lab_id, outputs.lab_title)
                evidence.absence_result = "passed"
                if operations.state_addresses():
                    raise ProtectedStagingError("protected state remains")
            except ProtectedStagingError:
                evidence.absence_result = "failed"
                evidence.cleanup_failure = FailureCode.ABSENCE_FAILED
            if evidence.absence_result == "passed":
                try:
                    retire_exact_run_directory(run_directory, run_id)
                    evidence.state_retirement_result = "passed"
                except (OSError, ProtectedStagingError):
                    evidence.state_retirement_result = "failed"
                    evidence.cleanup_failure = FailureCode.RETIREMENT_FAILED
        elif not create_attempted and evidence.cleanup_result == "passed":
            try:
                retire_exact_run_directory(run_directory, run_id)
                evidence.state_retirement_result = "passed"
            except (OSError, ProtectedStagingError):
                evidence.state_retirement_result = "failed"
                evidence.cleanup_failure = FailureCode.RETIREMENT_FAILED
    evidence.overall_result = (
        "passed"
        if evidence.primary_failure is None and evidence.cleanup_failure is None
        else "failed"
    )
    return evidence


def retire_exact_run_directory(run_directory: Path, run_id: str) -> None:
    """Delete only the exact empty-after-cleanup protected run directory."""
    if (
        run_directory.name != run_id
        or run_directory.parent.name != "ephemeral"
        or run_directory.is_symlink()
        or not run_directory.is_dir()
    ):
        raise ProtectedStagingError("protected state retirement rejected")
    shutil.rmtree(run_directory)


def recover_protected_run(
    build_id: UUID,
    state_root: Path,
    checkout: Path,
    manifest: ProtectedStagingManifest,
    operations: ProtectedLifecycleOperations,
) -> None:
    """Destroy one exact retained subset; never create or start."""
    run_id = f"bk-{build_id}"
    run_directory = state_root / "ephemeral" / run_id
    if run_directory.is_symlink() or not run_directory.is_dir():
        raise ProtectedStagingError("protected recovery run unavailable")
    metadata = load_recovery_metadata(
        run_directory / "recovery-metadata.json", checkout, manifest
    )
    if metadata.build_id != build_id or metadata.run_id != run_id:
        raise ProtectedStagingError("protected recovery identity mismatch")
    state = operations.state_addresses()
    if not state.issubset(EXPECTED_TERRAFORM_ADDRESSES):
        raise ProtectedStagingError("protected recovery graph rejected")
    if state:
        operations.cleanup_retained()
        if operations.state_addresses():
            raise ProtectedStagingError("protected recovery state remains")
    if metadata.lab_id is None:
        operations.prove_title_absent(metadata.lab_title)
    else:
        operations.prove_absent(metadata.lab_id, metadata.lab_title)
    if operations.state_addresses():
        raise ProtectedStagingError("protected recovery state remains")
    retire_exact_run_directory(run_directory, run_id)


def verify_ca_digest(pem: bytes, manifest: ProtectedStagingManifest) -> None:
    """Bind external CA material to immutable manifest authority."""
    if hashlib.sha256(pem).hexdigest() != manifest.cml.ca_pem_sha256:
        raise ProtectedStagingError("protected CML CA digest mismatch")


def build_cml_ssl_context(
    pem: bytes, manifest: ProtectedStagingManifest
) -> ssl.SSLContext:
    """Create explicit CML trust only from digest-admitted CA PEM."""
    verify_ca_digest(pem, manifest)
    try:
        return ssl.create_default_context(cadata=pem.decode("ascii"))
    except (UnicodeDecodeError, ssl.SSLError):
        raise ProtectedStagingError("protected CML CA invalid") from None
