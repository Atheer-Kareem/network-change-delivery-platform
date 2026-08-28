from __future__ import annotations

import hashlib
import inspect
import json
import stat
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest
from pydantic import ValidationError

from network_change_delivery.buildkite_staging import BuildkiteStagingContext
from network_change_delivery.protected_staging import (
    EXPECTED_TERRAFORM_ADDRESSES,
    CMLAuthority,
    ExecutionToolAuthority,
    NativeDependencyAuthority,
    ProtectedStagingError,
    ProtectedStagingManifest,
    ProtectedStagingTarget,
    ProtectedTerraformExecutor,
    ProtectedTerraformOutputs,
    ServiceIdentityAuthority,
    StagingTargetAuthority,
)
from network_change_delivery.protected_staging_controller import (
    ProtectedStagingController,
)
from network_change_delivery.protected_staging_runtime import (
    FailureCode,
    LifecycleIdentity,
    ProcessIdentity,
    ProtectedOperationError,
    ProtectedRecoveryMetadata,
    ProtectedRuntimeEvidence,
    ProtectedStaticInventory,
    build_protected_terraform_environment,
    derive_run_directory,
    directory_inventory_sha256,
    read_protected_file,
    read_root_owned_service_file,
    recover_protected_run,
    run_protected_lifecycle,
    validate_macho_dependencies,
    validate_native_runtime_authority,
    validate_protected_executable,
    validate_root_owned_executable,
    validate_root_owned_immutable_tree,
    validate_root_owned_service_directory,
    validate_service_identity,
    validate_service_owned_private_path,
    verify_ca_digest,
    write_recovery_metadata,
)

PIPELINE = UUID("00000000-0000-0000-0000-000000000001")
BUILD = UUID("00000000-0000-0000-0000-000000000002")
JOB = UUID("00000000-0000-0000-0000-000000000003")
LAB = UUID("11111111-1111-1111-1111-111111111111")
SHA1 = "a" * 40
SHA256 = "b" * 64


def target(device_id: int) -> StagingTargetAuthority:
    cisco = device_id == 6
    return StagingTargetAuthority(
        device_id=device_id,
        name="stg-core-02" if cisco else "stg-edge-junos-01",
        site_id=1,
        device_type_id=1 if cisco else 2,
        environment="staging",
        status="staged",
        role_slug="ncdp-staging",
        platform_slug="cisco-ios-xe" if cisco else "juniper-junos",
        management_interface="GigabitEthernet1" if cisco else "fxp0",
        management_interface_id=9 if cisco else 10,
        management_interface_type="1000base-t",
        management_interface_enabled=True,
        management_interface_mgmt_only=False,
        management_ip_address_id=9 if cisco else 10,
        management_cidr="192.168.4.30/24" if cisco else "192.168.4.31/24",
        management_ip="192.168.4.30" if cisco else "192.168.4.31",
        live_homolog_id=1 if cisco else 2,
        live_homolog_name="core-02" if cisco else "edge-junos-01",
        live_primary_cidr="192.168.4.14/24" if cisco else "192.168.4.20/24",
        openbao_role=f"ncdp-buildkite-staging-device-{device_id}",
        credential_reference=f"openbao:kv-v2:ncdp/devices/{device_id}/ssh",
    )


def manifest(**changes) -> ProtectedStagingManifest:
    controller = "src/network_change_delivery/protected_staging_controller.py"
    values = {
        "schema_version": 4,
        "service_identity": ServiceIdentityAuthority(service_uid=420, service_gid=420),
        "buildkite_pipeline_id": PIPELINE,
        "source_commit": SHA1,
        "netbox_url": "https://netbox.example",
        "openbao_url": "https://bao.example",
        "source_bundle_digest": SHA256,
        "source_inventory_sha256": SHA256,
        "runtime_inventory_sha256": SHA256,
        "runtime_digest": SHA256,
        "python_interpreter_path": "/opt/protected/python3.12",
        "python_interpreter_sha256": SHA256,
        "project_wheel_sha256": SHA256,
        "production_requirements_sha256": SHA256,
        "uv": ExecutionToolAuthority(
            path="/protected/uv", sha256=SHA256, version="0.12.2"
        ),
        "buildkite_agent": ExecutionToolAuthority(
            path="/protected/buildkite-agent", sha256=SHA256, version="3.137.0"
        ),
        "terraform": ExecutionToolAuthority(
            path="/protected/terraform", sha256=SHA256, version="1.15.8"
        ),
        "openssl": ExecutionToolAuthority(
            path="/protected/openssl", sha256=SHA256, version="3.6.3"
        ),
        "ssh_keyscan": ExecutionToolAuthority(
            path="/usr/bin/ssh-keyscan",
            sha256=SHA256,
            version="OpenSSH_10.2",
            system_protected=True,
        ),
        "ssh_keygen": ExecutionToolAuthority(
            path="/usr/bin/ssh-keygen",
            sha256=SHA256,
            version="OpenSSH_10.2",
            system_protected=True,
        ),
        "ansible_collections_root": "/protected/ansible",
        "ansible_collections": {
            "ansible.netcommon": "8.6.0",
            "ansible.utils": "6.1.0",
            "cisco.ios": "11.4.2",
        },
        "ansible_inventory_sha256": SHA256,
        "native_dependencies": (
            NativeDependencyAuthority(
                name="libssh",
                version="0.11.3",
                root="/private/var/db/ncdp-staging/authority/native/libssh",
                inventory_sha256=SHA256,
            ),
            NativeDependencyAuthority(
                name="openssl",
                version="3.6.3",
                root="/private/var/db/ncdp-staging/authority/native/openssl",
                inventory_sha256=SHA256,
            ),
        ),
        "protected_native_files": {
            "/private/var/db/ncdp-staging/authority/native/libssh/libssh.dylib": SHA256
        },
        "native_dependency_admission_sha256": SHA256,
        "build_sdk_identity": "macos-sdk-test",
        "controller_artifact_digest": SHA256,
        "file_digests": {controller: SHA256},
        "cisco": target(6),
        "junos": target(7),
        "live_deny_device_ids": (1, 2, 3),
        "live_deny_management_ips": (
            "192.168.4.14",
            "192.168.4.15",
            "192.168.4.20",
        ),
        "cml": CMLAuthority(
            controller_identity="personal-cml",
            controller_url="https://cml.example",
            ca_pem_sha256=SHA256,
        ),
        "terraform_addresses": tuple(sorted(EXPECTED_TERRAFORM_ADDRESSES)),
        "lifecycle_update_address": ("module.managed_pair.cml2_lifecycle.managed_pair"),
    }
    values.update(changes)
    return ProtectedStagingManifest.model_validate(values)


def outputs(run_id: str) -> ProtectedTerraformOutputs:
    return ProtectedTerraformOutputs(
        staging_run_id=run_id,
        lab_title=f"NCDP Staging {run_id}",
        lab_id=LAB,
        node_ids={
            "system_bridge": UUID("10000000-0000-0000-0000-000000000001"),
            "management_switch": UUID("10000000-0000-0000-0000-000000000002"),
            "cisco": UUID("10000000-0000-0000-0000-000000000003"),
            "junos": UUID("10000000-0000-0000-0000-000000000004"),
        },
        link_ids={
            "system_bridge_management": UUID("20000000-0000-0000-0000-000000000001"),
            "management_cisco": UUID("20000000-0000-0000-0000-000000000002"),
            "management_junos": UUID("20000000-0000-0000-0000-000000000003"),
            "cisco_junos": UUID("20000000-0000-0000-0000-000000000004"),
        },
        lifecycle_state="DEFINED_ON_CORE",
    )


def identity() -> LifecycleIdentity:
    return LifecycleIdentity(PIPELINE, BUILD, JOB, SHA1, SHA256, SHA256)


class FakeOperations:
    def __init__(
        self,
        *,
        state: set[str] | None = None,
        failure: str | None = None,
    ) -> None:
        self.state = set(EXPECTED_TERRAFORM_ADDRESSES) if state is None else set(state)
        self.failure = failure
        self.calls: list[str] = []

    def _call(self, name: str) -> None:
        self.calls.append(name)
        if self.failure == name:
            raise ProtectedStagingError(f"sanitized {name}")

    def admit(self) -> None:
        self._call("admit")

    def create(self) -> ProtectedTerraformOutputs:
        self._call("create")
        return outputs(f"bk-{BUILD}")

    def verify_realization(self, _outputs) -> None:
        self._call("verify")

    def start(self) -> None:
        self._call("start")

    def readiness(self) -> dict[str, float]:
        self._call("readiness")
        return {"cisco_tcp22": 1.0, "junos_tcp830": 2.0}

    def establish_host_trust(self) -> None:
        self._call("trust")

    def validate_read_only(self) -> dict[str, int]:
        self._call("validate")
        return {"cisco": 1, "junos": 1}

    def state_addresses(self) -> set[str]:
        self.calls.append("state")
        return set(self.state)

    def cleanup_retained(self) -> bool:
        self._call("cleanup")
        self.state.clear()
        return True

    def prove_absent(self, _lab_id, _lab_title) -> None:
        self._call("absent")

    def prove_title_absent(self, _lab_title) -> None:
        self._call("absent-title")


def run_directory(tmp_path: Path) -> Path:
    root = tmp_path / "state"
    root.mkdir(mode=0o700)
    _run_id, directory = derive_run_directory(root, BUILD)
    return directory


def test_schema_four_binds_pipeline_endpoints_source_runtime_and_service() -> None:
    assert manifest().schema_version == 4
    with pytest.raises(ValidationError):
        manifest(buildkite_pipeline_id="not-a-uuid")
    with pytest.raises(ValidationError):
        manifest(netbox_url="https://other.example/path")
    with pytest.raises(ValidationError):
        manifest(openbao_url="http://bao.example")


def test_sanitized_admission_uses_manifest_schema() -> None:
    controller = object.__new__(ProtectedStagingController)
    controller.manifest = manifest()
    controller.context = BuildkiteStagingContext(
        pipeline_id=str(PIPELINE),
        build_id=str(BUILD),
        commit=SHA1,
        branch="main",
        step_key="cml-staging",
        job_id=str(JOB),
        queue_key="ncdp-staging",
        retry_count="0",
    )
    assert controller.admit()["schema_version"] == 4


def test_controller_revalidates_native_and_ansible_before_secret_reads() -> None:
    source = inspect.getsource(ProtectedStagingController.load.__func__)
    native = source.index("validate_native_runtime_authority")
    ansible = source.index("validate_root_owned_immutable_tree")
    secret = source.index("netbox_token = read_root_owned_service_file")
    assert native < secret
    assert ansible < secret


def _metadata(uid: int, gid: int, mode: int, size: int = 1):
    return SimpleNamespace(st_uid=uid, st_gid=gid, st_mode=mode, st_size=size)


def test_exact_service_identity_rejects_root_validation_and_groups() -> None:
    authority = manifest().service_identity
    validate_service_identity(authority, ProcessIdentity(420, 420, ()))
    for identity in (
        ProcessIdentity(0, 420, ()),
        ProcessIdentity(501, 420, ()),
        ProcessIdentity(420, 421, ()),
        ProcessIdentity(420, 420, (20,)),
    ):
        with pytest.raises(ProtectedStagingError):
            validate_service_identity(authority, identity)
    for uid, gid in ((420, 20), (420, 80), (501, 501)):
        with pytest.raises(ValidationError):
            ServiceIdentityAuthority(service_uid=uid, service_gid=gid)
    with pytest.raises(ValidationError):
        ServiceIdentityAuthority(
            service_uid=420, service_gid=420, supplementary_gids=(20,)
        )


def test_root_owned_config_and_service_owned_state_policies(tmp_path: Path) -> None:
    checkout = tmp_path / "checkout"
    authority_root = tmp_path / "protected/authority"
    service_root = tmp_path / "protected"
    system_parent = tmp_path
    config_dir = authority_root / "config"
    state_root = tmp_path / "protected/state"
    checkout.mkdir()
    config_dir.mkdir(parents=True)
    state_root.mkdir()
    config = config_dir / "protected-controller.json"
    config.write_text("{}", encoding="utf-8")
    authority = manifest().service_identity

    def admitted(path: Path):
        if path == config:
            return _metadata(0, 420, stat.S_IFREG | 0o440, 2)
        if path == config_dir:
            return _metadata(0, 420, stat.S_IFDIR | 0o750)
        if path == state_root:
            return _metadata(420, 420, stat.S_IFDIR | 0o700)
        if path == service_root:
            return _metadata(0, 420, stat.S_IFDIR | 0o750)
        return _metadata(0, 0, stat.S_IFDIR | 0o755)

    assert (
        read_root_owned_service_file(
            config,
            checkout,
            authority,
            authority_root=authority_root,
            service_root=service_root,
            system_parent=system_parent,
            metadata_reader=admitted,
        )
        == b"{}"
    )
    assert (
        validate_root_owned_service_directory(
            config_dir,
            checkout,
            authority,
            authority_root=authority_root,
            service_root=service_root,
            system_parent=system_parent,
            metadata_reader=admitted,
        )
        == config_dir
    )
    assert (
        validate_service_owned_private_path(
            state_root,
            checkout,
            authority,
            mutable_root=tmp_path / "protected",
            system_parent=system_parent,
            metadata_reader=admitted,
        )
        == state_root
    )
    for uid, gid in ((421, 420), (420, 421)):
        with pytest.raises(ProtectedStagingError):
            validate_service_owned_private_path(
                state_root,
                checkout,
                authority,
                mutable_root=tmp_path / "protected",
                metadata_reader=lambda path, uid=uid, gid=gid: (
                    _metadata(uid, gid, stat.S_IFDIR | 0o700)
                    if path == state_root
                    else admitted(path)
                ),
            )

    def staging_owned(path: Path):
        value = admitted(path)
        if path == config:
            return _metadata(420, 420, value.st_mode, value.st_size)
        return value

    with pytest.raises(ProtectedStagingError):
        read_root_owned_service_file(
            config,
            checkout,
            authority,
            authority_root=authority_root,
            service_root=service_root,
            system_parent=system_parent,
            metadata_reader=staging_owned,
        )
    with pytest.raises(ProtectedStagingError):
        validate_root_owned_service_directory(
            config_dir,
            checkout,
            authority,
            authority_root=authority_root,
            service_root=service_root,
            system_parent=system_parent,
            metadata_reader=lambda path: (
                _metadata(420, 420, stat.S_IFDIR | 0o550)
                if path == config_dir
                else admitted(path)
            ),
        )

    for unsafe in (
        _metadata(420, 420, stat.S_IFDIR | 0o750),
        _metadata(0, 420, stat.S_IFDIR | 0o770),
        _metadata(0, 420, stat.S_IFDIR | 0o757),
    ):
        unsafe_parent = lambda path, unsafe=unsafe: (  # noqa: E731
            unsafe if path == service_root else admitted(path)
        )
        with pytest.raises(ProtectedStagingError):
            read_root_owned_service_file(
                config,
                checkout,
                authority,
                authority_root=authority_root,
                service_root=service_root,
                system_parent=system_parent,
                metadata_reader=unsafe_parent,
            )
        with pytest.raises(ProtectedStagingError):
            validate_service_owned_private_path(
                state_root,
                checkout,
                authority,
                mutable_root=service_root,
                system_parent=system_parent,
                metadata_reader=unsafe_parent,
            )
    arbitrary = service_root / "arbitrary"
    arbitrary.mkdir()
    with pytest.raises(ProtectedStagingError):
        validate_service_owned_private_path(
            arbitrary,
            checkout,
            authority,
            mutable_root=service_root,
            system_parent=system_parent,
            metadata_reader=lambda path: (
                _metadata(420, 420, stat.S_IFDIR | 0o700)
                if path == arbitrary
                else admitted(path)
            ),
        )


def test_tool_digest_and_native_dependency_admission(tmp_path: Path) -> None:
    checkout = tmp_path / "checkout"
    service_root = tmp_path / "protected"
    authority_root = service_root / "authority"
    tool_dir = authority_root / "tools"
    checkout.mkdir()
    tool_dir.mkdir(parents=True)
    tool = tool_dir / "terraform"
    tool.write_bytes(b"terraform")
    tool.chmod(0o550)
    authority = manifest().service_identity
    tool_authority = manifest().terraform.model_copy(
        update={"path": str(tool), "sha256": hashlib.sha256(b"terraform").hexdigest()}
    )

    def metadata(path: Path):
        if path == tool:
            return _metadata(0, 420, stat.S_IFREG | 0o550, len(b"terraform"))
        if path == service_root:
            return _metadata(0, 420, stat.S_IFDIR | 0o750)
        return _metadata(0, 0, stat.S_IFDIR | 0o755)

    validate_root_owned_executable(
        tool,
        checkout,
        authority,
        tool_authority,
        authority_root=authority_root,
        service_root=service_root,
        system_parent=tmp_path,
        metadata_reader=metadata,
        observed_version="1.15.8",
    )
    with pytest.raises(ProtectedStagingError):
        validate_root_owned_executable(
            tool,
            checkout,
            authority,
            tool_authority,
            authority_root=authority_root,
            service_root=service_root,
            system_parent=tmp_path,
            metadata_reader=lambda path: (
                _metadata(0, 0, stat.S_IFDIR | 0o775)
                if path == tool_dir
                else metadata(path)
            ),
        )
    with pytest.raises(ProtectedStagingError):
        validate_root_owned_executable(
            tool,
            checkout,
            authority,
            tool_authority.model_copy(update={"sha256": "0" * 64}),
            authority_root=authority_root,
            service_root=service_root,
            system_parent=tmp_path,
            metadata_reader=metadata,
        )
    with pytest.raises(ProtectedStagingError):
        validate_root_owned_executable(
            tool,
            checkout,
            authority,
            tool_authority,
            authority_root=authority_root,
            service_root=service_root,
            system_parent=tmp_path,
            metadata_reader=metadata,
            observed_version="1.16.0",
        )

    protected = Path(
        "/private/var/db/ncdp-staging/authority/native/libssh/libssh.dylib"
    )
    validate_macho_dependencies(
        {
            "/protected/runtime/module.so": (
                "/usr/lib/libSystem.B.dylib",
                str(protected),
            )
        },
        protected_native_files={protected: SHA256},
        digest_reader=lambda _path: SHA256,
    )
    for rejected in (
        "/opt/homebrew/lib/libssh.dylib",
        "/Users/netdevops/libssh.dylib",
        "/private/tmp/build/libssh.dylib",
        "@rpath/libssh.dylib",
        "@loader_path/libssh.dylib",
        "@executable_path/libssh.dylib",
    ):
        with pytest.raises(ProtectedStagingError):
            validate_macho_dependencies(
                {"/protected/runtime/module.so": (rejected,)},
                protected_native_files={},
                digest_reader=lambda _path: SHA256,
            )

    collections = tmp_path / "collections"
    collections.mkdir()
    metadata_file = collections / "MANIFEST.json"
    metadata_file.write_text('{"version":"8.6.0"}', encoding="utf-8")
    before = directory_inventory_sha256(collections)
    metadata_file.write_text('{"version":"8.6.1"}', encoding="utf-8")
    assert directory_inventory_sha256(collections) != before


def test_native_authority_is_revalidated_from_exact_roots(tmp_path: Path) -> None:
    checkout = tmp_path / "checkout"
    service_root = tmp_path / "protected"
    authority_root = service_root / "authority"
    native_root = authority_root / "native"
    runtime = authority_root / "install/runtime"
    checkout.mkdir()
    runtime.mkdir(parents=True)
    native_dependencies = []
    protected_files = {}
    for name, version in (("libssh", "0.11.3"), ("openssl", "3.6.3")):
        root = native_root / name
        root.mkdir(parents=True)
        (root / "VERSION").write_text(version + "\n", encoding="utf-8")
        library = root / f"lib{name}.dylib"
        library.write_bytes(name.encode())
        for path in (root / "VERSION", library):
            path.chmod(0o440)
        root.chmod(0o550)
        native_dependencies.append(
            NativeDependencyAuthority(
                name=name,
                version=version,
                root=str(root),
                inventory_sha256=directory_inventory_sha256(root),
            )
        )
        protected_files[str(library)] = hashlib.sha256(library.read_bytes()).hexdigest()
    dependency_map = {
        str(runtime / "module.so"): (
            "/usr/lib/libSystem.B.dylib",
            str(native_root / "libssh/liblibssh.dylib"),
        )
    }
    admission = hashlib.sha256(
        json.dumps(dependency_map, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    admitted_manifest = manifest().model_copy(
        update={
            "native_dependencies": tuple(native_dependencies),
            "protected_native_files": protected_files,
            "native_dependency_admission_sha256": admission,
        }
    )

    def metadata(path: Path):
        if path == service_root:
            return _metadata(0, 420, stat.S_IFDIR | 0o750)
        if path == tmp_path:
            return _metadata(0, 0, stat.S_IFDIR | 0o755)
        if path.is_dir():
            return _metadata(0, 420, stat.S_IFDIR | stat.S_IMODE(path.stat().st_mode))
        return _metadata(
            0,
            420,
            stat.S_IFREG | stat.S_IMODE(path.stat().st_mode),
            path.stat().st_size,
        )

    validate_native_runtime_authority(
        admitted_manifest,
        runtime,
        checkout,
        dependency_inspector=lambda _root: dependency_map,
        authority_root=authority_root,
        service_root=service_root,
        system_parent=tmp_path,
        metadata_reader=metadata,
    )
    library = native_root / "libssh/liblibssh.dylib"
    library.chmod(0o600)
    library.write_bytes(b"tampered")
    library.chmod(0o440)
    with pytest.raises(ProtectedStagingError):
        validate_native_runtime_authority(
            admitted_manifest,
            runtime,
            checkout,
            dependency_inspector=lambda _root: dependency_map,
            authority_root=authority_root,
            service_root=service_root,
            system_parent=tmp_path,
            metadata_reader=metadata,
        )
    library.chmod(0o600)
    library.write_bytes(b"libssh")
    library.chmod(0o440)
    with pytest.raises(ProtectedStagingError, match="admission changed"):
        validate_native_runtime_authority(
            admitted_manifest,
            runtime,
            checkout,
            dependency_inspector=lambda _root: {
                **dependency_map,
                str(runtime / "other.so"): ("/usr/lib/libSystem.B.dylib",),
            },
            authority_root=authority_root,
            service_root=service_root,
            system_parent=tmp_path,
            metadata_reader=metadata,
        )


def test_ansible_tree_requires_exact_versions_ownership_and_inventory(
    tmp_path: Path,
) -> None:
    checkout = tmp_path / "checkout"
    service_root = tmp_path / "protected"
    authority_root = service_root / "authority"
    collections = authority_root / "ansible"
    checkout.mkdir()
    expected = {
        "ansible.netcommon": "8.6.0",
        "ansible.utils": "6.1.0",
        "cisco.ios": "11.4.2",
    }
    for name, version in expected.items():
        namespace, collection = name.split(".")
        root = collections / "ansible_collections" / namespace / collection
        root.mkdir(parents=True)
        (root / "MANIFEST.json").write_text(
            json.dumps({"collection_info": {"version": version}}), encoding="utf-8"
        )
    for path in collections.rglob("*"):
        path.chmod(0o550 if path.is_dir() else 0o440)
    collections.chmod(0o550)
    inventory = directory_inventory_sha256(collections)

    def metadata(path: Path):
        if path == service_root:
            return _metadata(0, 420, stat.S_IFDIR | 0o750)
        if path == tmp_path:
            return _metadata(0, 0, stat.S_IFDIR | 0o755)
        mode = stat.S_IMODE(path.stat().st_mode)
        return _metadata(
            0, 420, (stat.S_IFDIR if path.is_dir() else stat.S_IFREG) | mode
        )

    validate_root_owned_immutable_tree(
        collections,
        checkout,
        manifest().service_identity,
        inventory,
        expected_collections=expected,
        authority_root=authority_root,
        service_root=service_root,
        system_parent=tmp_path,
        metadata_reader=metadata,
    )
    with pytest.raises(ProtectedStagingError, match="version"):
        validate_root_owned_immutable_tree(
            collections,
            checkout,
            manifest().service_identity,
            inventory,
            expected_collections={**expected, "cisco.ios": "11.4.3"},
            authority_root=authority_root,
            service_root=service_root,
            system_parent=tmp_path,
            metadata_reader=metadata,
        )
    nested = next(path for path in collections.rglob("MANIFEST.json"))
    with pytest.raises(ProtectedStagingError, match="immutable tree"):
        validate_root_owned_immutable_tree(
            collections,
            checkout,
            manifest().service_identity,
            inventory,
            expected_collections=expected,
            authority_root=authority_root,
            service_root=service_root,
            system_parent=tmp_path,
            metadata_reader=lambda path: (
                _metadata(0, 420, stat.S_IFREG | 0o460)
                if path == nested
                else metadata(path)
            ),
        )


def test_protected_file_rejects_mode_symlink_empty_and_checkout(tmp_path: Path) -> None:
    checkout = tmp_path / "checkout"
    external = tmp_path / "external"
    checkout.mkdir()
    external.mkdir()
    secret = external / "secret"
    secret.write_text("value", encoding="utf-8")
    secret.chmod(0o600)
    assert read_protected_file(secret, checkout) == b"value"
    secret.chmod(0o640)
    with pytest.raises(ProtectedStagingError):
        read_protected_file(secret, checkout)
    secret.chmod(0o600)
    link = external / "link"
    link.symlink_to(secret)
    with pytest.raises(ProtectedStagingError):
        read_protected_file(link, checkout)
    empty = external / "empty"
    empty.touch(mode=0o600)
    with pytest.raises(ProtectedStagingError):
        read_protected_file(empty, checkout)
    inside = checkout / "secret"
    inside.write_text("value", encoding="utf-8")
    inside.chmod(0o600)
    with pytest.raises(ProtectedStagingError):
        read_protected_file(inside, checkout)


def test_protected_tool_requires_absolute_private_non_checkout_path(
    tmp_path: Path,
) -> None:
    checkout = tmp_path / "checkout"
    external = tmp_path / "tools"
    checkout.mkdir()
    external.mkdir()
    tool = external / "terraform"
    tool.write_text("#!/bin/sh\n", encoding="utf-8")
    tool.chmod(0o700)
    assert (
        validate_protected_executable(
            tool,
            checkout,
            expected_version="1.15.8",
            version_runner=lambda _path, _args: "1.15.8",
        )
        == tool
    )
    tool.chmod(0o720)
    with pytest.raises(ProtectedStagingError):
        validate_protected_executable(tool, checkout)


def test_terraform_environment_is_constructed_not_inherited(monkeypatch) -> None:
    monkeypatch.setenv("TF_LOG", "TRACE")
    monkeypatch.setenv("NCDP_NETBOX_TOKEN", "forbidden")
    variables = {
        "TF_VAR_staging_run_id": f"bk-{BUILD}",
        "TF_VAR_lifecycle_state": "DEFINED_ON_CORE",
        "TF_VAR_cisco_bootstrap_hostname": "stg-core-02",
        "TF_VAR_cisco_bootstrap_management_cidr": "192.168.4.30/24",
        "TF_VAR_cisco_bootstrap_username": "cisco-user",
        "TF_VAR_cisco_bootstrap_password": "cisco-password",
        "TF_VAR_junos_bootstrap_hostname": "stg-edge-junos-01",
        "TF_VAR_junos_bootstrap_management_cidr": "192.168.4.31/24",
        "TF_VAR_junos_bootstrap_username": "junos-user",
        "TF_VAR_junos_bootstrap_password_hash": "$6$salt$hash",
    }
    environment = build_protected_terraform_environment(
        terraform_data_dir=Path("/protected/data"),
        cml_address="https://cml.example",
        cml_token="memory-only",
        cml_ca_pem="pem",
        variables=variables,
        trusted_path="/protected/bin",
    )
    assert set(environment) == {
        "PATH",
        "TF_IN_AUTOMATION",
        "TF_DATA_DIR",
        "CML2_ADDRESS",
        "CML2_TOKEN",
        "CML2_CACERT",
        *variables,
    }
    assert "TF_LOG" not in environment and "NCDP_NETBOX_TOKEN" not in environment


def test_static_inventory_accepts_only_exact_pair() -> None:
    targets = (
        ProtectedStagingTarget(
            device_id=6,
            name="stg-core-02",
            host="192.168.4.30",
            platform="cisco_iosxe",
            management_interface="GigabitEthernet1",
            interface_id=9,
            management_cidr="192.168.4.30/24",
            ip_address_id=9,
            live_homolog_id=1,
            credential_reference="openbao:kv-v2:ncdp/devices/6/ssh",
            openbao_role="ncdp-buildkite-staging-device-6",
        ),
        ProtectedStagingTarget(
            device_id=7,
            name="stg-edge-junos-01",
            host="192.168.4.31",
            platform="junos",
            management_interface="fxp0",
            interface_id=10,
            management_cidr="192.168.4.31/24",
            ip_address_id=10,
            live_homolog_id=2,
            credential_reference="openbao:kv-v2:ncdp/devices/7/ssh",
            openbao_role="ncdp-buildkite-staging-device-7",
        ),
    )
    inventory = ProtectedStaticInventory(targets)
    assert inventory.resolve("stg-core-02").port == 22
    assert inventory.resolve("stg-edge-junos-01").port == 830
    integration = inventory.resolve("stg-core-02", "GigabitEthernet2")
    assert integration.inventory_interface_object_id == (
        "protected:cml.integration:6:GigabitEthernet2"
    )
    with pytest.raises(ProtectedStagingError):
        inventory.resolve("stg-core-02", "GigabitEthernet3")
    with pytest.raises(ProtectedStagingError):
        inventory.resolve("core-02")


def test_complete_lifecycle_cleans_absence_proves_and_retires(tmp_path: Path) -> None:
    directory = run_directory(tmp_path)
    operations = FakeOperations()
    evidence = run_protected_lifecycle(identity(), directory, operations)
    assert evidence.overall_result == "passed"
    assert evidence.cleanup_result == "passed"
    assert evidence.absence_result == "passed"
    assert evidence.state_retirement_result == "passed"
    assert not directory.exists()
    assert operations.calls.count("cleanup") == 1


@pytest.mark.parametrize("count", [1, 5, 10])
def test_create_failure_valid_partial_state_gets_one_exact_cleanup(
    tmp_path: Path, count: int
) -> None:
    directory = run_directory(tmp_path)
    state = set(sorted(EXPECTED_TERRAFORM_ADDRESSES)[:count])
    operations = FakeOperations(state=state, failure="create")
    evidence = run_protected_lifecycle(identity(), directory, operations)
    assert evidence.overall_result == "failed"
    assert evidence.primary_failure == FailureCode.TERRAFORM_CREATE
    assert evidence.cleanup_result == "passed"
    assert evidence.absence_result == "passed"
    assert operations.calls.count("cleanup") == 1
    assert "absent-title" in operations.calls
    assert not directory.exists()


def test_create_failure_with_empty_state_never_destroys(tmp_path: Path) -> None:
    directory = run_directory(tmp_path)
    operations = FakeOperations(state=set(), failure="create")
    evidence = run_protected_lifecycle(identity(), directory, operations)
    assert "cleanup" not in operations.calls
    assert evidence.cleanup_result == "passed"
    assert evidence.absence_result == "passed"
    assert "absent-title" in operations.calls
    assert evidence.state_retirement_result == "passed"
    assert not directory.exists()


def test_create_attempt_without_state_retains_when_title_is_present(
    tmp_path: Path,
) -> None:
    directory = run_directory(tmp_path)
    operations = FakeOperations(state=set(), failure="absent-title")
    operations.failure = "create"
    original = operations.prove_title_absent

    def fail_title(title) -> None:
        original(title)
        raise ProtectedStagingError("sanitized title conflict")

    operations.prove_title_absent = fail_title
    evidence = run_protected_lifecycle(identity(), directory, operations)
    assert evidence.absence_result == "failed"
    assert evidence.cleanup_failure == FailureCode.ABSENCE_FAILED
    assert directory.exists()


def test_admission_failure_retires_empty_run_without_cml_claim(tmp_path: Path) -> None:
    directory = run_directory(tmp_path)
    operations = FakeOperations(state=set(), failure="admit")
    evidence = run_protected_lifecycle(identity(), directory, operations)
    assert "create" not in operations.calls
    assert "cleanup" not in operations.calls
    assert "absent-title" not in operations.calls
    assert evidence.state_retirement_result == "passed"
    assert not directory.exists()


def test_terraform_init_has_distinct_sanitized_failure_code(tmp_path: Path) -> None:
    directory = run_directory(tmp_path)
    operations = FakeOperations(state=set())

    def fail_init() -> None:
        operations.calls.append("admit")
        raise ProtectedOperationError(FailureCode.TERRAFORM_INIT)

    operations.admit = fail_init
    evidence = run_protected_lifecycle(identity(), directory, operations)
    assert evidence.primary_failure == FailureCode.TERRAFORM_INIT
    assert evidence.safe_json().find("TERRAFORM_INIT") >= 0
    assert "absent-title" not in operations.calls


def test_foreign_state_is_retained_without_destroy(tmp_path: Path) -> None:
    directory = run_directory(tmp_path)
    operations = FakeOperations(state={"foreign.resource"}, failure="create")
    evidence = run_protected_lifecycle(identity(), directory, operations)
    assert evidence.cleanup_result == "retained"
    assert evidence.cleanup_failure == FailureCode.CLEANUP_UNAUTHORIZED
    assert "cleanup" not in operations.calls
    assert directory.exists()


@pytest.mark.parametrize("failure", ["cleanup", "absent"])
def test_failures_preserve_independent_cleanup_state(
    tmp_path: Path, failure: str
) -> None:
    directory = run_directory(tmp_path)
    operations = FakeOperations(failure=failure)
    evidence = run_protected_lifecycle(identity(), directory, operations)
    assert evidence.overall_result == "failed"
    assert directory.exists()
    if failure == "cleanup":
        assert evidence.cleanup_failure == FailureCode.CLEANUP_FAILED
    else:
        assert evidence.cleanup_failure == FailureCode.ABSENCE_FAILED


def test_validation_failure_with_proven_cleanup_retires_state(tmp_path: Path) -> None:
    directory = run_directory(tmp_path)
    evidence = run_protected_lifecycle(
        identity(), directory, FakeOperations(failure="validate")
    )
    assert evidence.overall_result == "failed"
    assert evidence.primary_failure == FailureCode.VALIDATION
    assert evidence.cleanup_result == "passed"
    assert not directory.exists()


def test_evidence_rejects_secret_fields_and_never_emits_injected_exception(
    tmp_path: Path,
) -> None:
    directory = run_directory(tmp_path)
    evidence = run_protected_lifecycle(
        identity(), directory, FakeOperations(failure="validate")
    )
    serialized = evidence.safe_json()
    assert "sanitized validate" not in serialized
    assert "password" not in serialized
    payload = json.loads(serialized)
    payload["token"] = "secret"
    with pytest.raises(ValidationError):
        ProtectedRuntimeEvidence.model_validate(payload)


def test_ca_digest_is_exact() -> None:
    pem = b"test-ca"
    accepted = manifest(
        cml=CMLAuthority(
            controller_identity="personal-cml",
            controller_url="https://cml.example",
            ca_pem_sha256=hashlib.sha256(pem).hexdigest(),
        )
    )
    verify_ca_digest(pem, accepted)
    with pytest.raises(ProtectedStagingError):
        verify_ca_digest(b"other", accepted)


class CleanupTerraformRunner:
    def __init__(self, state: set[str], planned: dict[str, str]) -> None:
        self.state = set(state)
        self.planned = planned
        self.calls = []

    def run(self, arguments, *, cwd, environment):
        del cwd, environment
        self.calls.append(tuple(arguments))
        if arguments[:2] == ["state", "list"]:
            return tuple(sorted(self.state))
        if arguments[0] == "plan":
            return tuple(
                json.dumps(
                    {
                        "type": "planned_change",
                        "change": {"resource": {"addr": address}, "action": action},
                    }
                )
                for address, action in self.planned.items()
            )
        if arguments[0] == "apply":
            self.state.clear()
        return ()


def test_executor_start_changes_only_protected_lifecycle_input(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    (bundle / "infrastructure/cml/ephemeral").mkdir(parents=True)
    state_dir = tmp_path / "state"
    state_dir.mkdir(mode=0o700)

    class StartRunner:
        def __init__(self) -> None:
            self.environment = {}

        def run(self, arguments, *, cwd, environment):
            del cwd
            self.environment = dict(environment)
            if arguments[0] == "plan":
                return (
                    json.dumps(
                        {
                            "type": "planned_change",
                            "change": {
                                "resource": {
                                    "addr": (
                                        "module.managed_pair.cml2_lifecycle.managed_pair"
                                    )
                                },
                                "action": "update",
                            },
                        }
                    ),
                )
            return ()

    runner = StartRunner()
    executor = ProtectedTerraformExecutor(
        bundle,
        state_dir,
        runner,
        {"TF_VAR_lifecycle_state": "DEFINED_ON_CORE"},
    )
    executor.set_lifecycle_state("STARTED")
    executor.execute("start")
    assert runner.environment["TF_VAR_lifecycle_state"] == "STARTED"


@pytest.mark.parametrize("count", [1, 5, 10])
def test_executor_partial_cleanup_applies_exact_subset(
    tmp_path: Path, count: int
) -> None:
    bundle = tmp_path / "bundle"
    (bundle / "infrastructure/cml/ephemeral").mkdir(parents=True)
    state_dir = tmp_path / "state"
    state_dir.mkdir(mode=0o700)
    (state_dir / "terraform.tfstate").touch(mode=0o600)
    state = set(sorted(EXPECTED_TERRAFORM_ADDRESSES)[:count])
    runner = CleanupTerraformRunner(state, dict.fromkeys(state, "delete"))
    executor = ProtectedTerraformExecutor(bundle, state_dir, runner, {})
    assert executor.cleanup_retained() is True
    assert not runner.state
    assert runner.calls[-1][0] == "apply"


@pytest.mark.parametrize(
    "state,planned",
    [
        ({"foreign.resource"}, {"foreign.resource": "delete"}),
        ({"cml2_lab.staging"}, {}),
        ({"cml2_lab.staging"}, {"cml2_lab.staging": "update"}),
        (
            {"cml2_lab.staging"},
            {"cml2_lab.staging": "delete", "foreign.resource": "delete"},
        ),
    ],
)
def test_executor_cleanup_rejects_foreign_or_mismatched_plan(
    tmp_path: Path, state, planned
) -> None:
    bundle = tmp_path / "bundle"
    (bundle / "infrastructure/cml/ephemeral").mkdir(parents=True)
    state_dir = tmp_path / "state"
    state_dir.mkdir(mode=0o700)
    (state_dir / "terraform.tfstate").touch(mode=0o600)
    runner = CleanupTerraformRunner(state, planned)
    executor = ProtectedTerraformExecutor(bundle, state_dir, runner, {})
    with pytest.raises(ProtectedStagingError):
        executor.cleanup_retained()
    assert not any(call[0] == "apply" for call in runner.calls)


def test_recovery_uses_exact_metadata_and_never_create_or_start(tmp_path: Path) -> None:
    checkout = tmp_path / "checkout"
    state_root = tmp_path / "state"
    checkout.mkdir()
    state_root.mkdir(mode=0o700)
    run_id, directory = derive_run_directory(state_root, BUILD)
    metadata = ProtectedRecoveryMetadata(
        run_id=run_id,
        build_id=BUILD,
        source_commit=SHA1,
        manifest_digest=manifest().digest,
        bundle_digest=SHA256,
        lab_id=LAB,
        lab_title=f"NCDP Staging {run_id}",
        terraform_addresses=tuple(sorted(EXPECTED_TERRAFORM_ADDRESSES)),
    )
    write_recovery_metadata(directory / "recovery-metadata.json", metadata)
    operations = FakeOperations(state={"cml2_lab.staging"})
    recover_protected_run(BUILD, state_root, checkout, manifest(), operations)
    assert "create" not in operations.calls and "start" not in operations.calls
    assert not directory.exists()


def test_recovery_rejects_wrong_bundle(tmp_path: Path) -> None:
    checkout = tmp_path / "checkout"
    state_root = tmp_path / "state"
    checkout.mkdir()
    state_root.mkdir(mode=0o700)
    run_id, directory = derive_run_directory(state_root, BUILD)
    metadata = ProtectedRecoveryMetadata(
        run_id=run_id,
        build_id=BUILD,
        source_commit=SHA1,
        manifest_digest="c" * 64,
        bundle_digest=SHA256,
        lab_id=LAB,
        lab_title=f"NCDP Staging {run_id}",
        terraform_addresses=tuple(sorted(EXPECTED_TERRAFORM_ADDRESSES)),
    )
    write_recovery_metadata(directory / "recovery-metadata.json", metadata)
    with pytest.raises(ProtectedStagingError, match="version mismatch"):
        recover_protected_run(BUILD, state_root, checkout, manifest(), FakeOperations())
    assert directory.exists()


def test_recovery_accepts_provisional_metadata_without_arbitrary_lab_id(
    tmp_path: Path,
) -> None:
    checkout = tmp_path / "checkout"
    state_root = tmp_path / "state"
    checkout.mkdir()
    state_root.mkdir(mode=0o700)
    run_id, directory = derive_run_directory(state_root, BUILD)
    metadata = ProtectedRecoveryMetadata(
        run_id=run_id,
        build_id=BUILD,
        source_commit=SHA1,
        manifest_digest=manifest().digest,
        bundle_digest=SHA256,
        lab_title=f"NCDP Staging {run_id}",
        terraform_addresses=tuple(sorted(EXPECTED_TERRAFORM_ADDRESSES)),
    )
    write_recovery_metadata(directory / "recovery-metadata.json", metadata)
    operations = FakeOperations(state={"cml2_lab.staging"})
    recover_protected_run(BUILD, state_root, checkout, manifest(), operations)
    assert "absent-title" in operations.calls
    assert "create" not in operations.calls and "start" not in operations.calls
    assert not directory.exists()


@pytest.mark.parametrize("final_metadata", [True, False])
def test_recovery_accepts_empty_post_destroy_state_and_proves_absence(
    tmp_path: Path, final_metadata: bool
) -> None:
    checkout = tmp_path / "checkout"
    state_root = tmp_path / "state"
    checkout.mkdir()
    state_root.mkdir(mode=0o700)
    run_id, directory = derive_run_directory(state_root, BUILD)
    metadata = ProtectedRecoveryMetadata(
        run_id=run_id,
        build_id=BUILD,
        source_commit=SHA1,
        manifest_digest=manifest().digest,
        bundle_digest=SHA256,
        lab_id=LAB if final_metadata else None,
        lab_title=f"NCDP Staging {run_id}",
        terraform_addresses=tuple(sorted(EXPECTED_TERRAFORM_ADDRESSES)),
    )
    write_recovery_metadata(directory / "recovery-metadata.json", metadata)
    operations = FakeOperations(state=set())
    recover_protected_run(BUILD, state_root, checkout, manifest(), operations)
    assert "cleanup" not in operations.calls
    assert ("absent" if final_metadata else "absent-title") in operations.calls
    assert not directory.exists()


def test_recovery_empty_state_retains_when_absence_fails(tmp_path: Path) -> None:
    checkout = tmp_path / "checkout"
    state_root = tmp_path / "state"
    checkout.mkdir()
    state_root.mkdir(mode=0o700)
    run_id, directory = derive_run_directory(state_root, BUILD)
    metadata = ProtectedRecoveryMetadata(
        run_id=run_id,
        build_id=BUILD,
        source_commit=SHA1,
        manifest_digest=manifest().digest,
        bundle_digest=SHA256,
        lab_title=f"NCDP Staging {run_id}",
        terraform_addresses=tuple(sorted(EXPECTED_TERRAFORM_ADDRESSES)),
    )
    write_recovery_metadata(directory / "recovery-metadata.json", metadata)
    operations = FakeOperations(state=set(), failure="absent-title")
    with pytest.raises(ProtectedStagingError):
        recover_protected_run(BUILD, state_root, checkout, manifest(), operations)
    assert "cleanup" not in operations.calls
    assert directory.exists()
