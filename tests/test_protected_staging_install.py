import shutil
import subprocess
import sys
from pathlib import Path
from uuid import UUID

import pytest

from network_change_delivery.protected_staging import (
    ProtectedStagingError,
    validate_runtime_artifacts,
    validate_runtime_inventory,
)
from network_change_delivery.protected_staging_install import (
    PROTECTED_SOURCE_FILES,
    SubprocessRuntimeBuildRunner,
    construct_isolated_runtime,
    install_source_bundle,
    inventory_runtime,
)


class FakeRuntimeBuilder:
    def __init__(self) -> None:
        self.calls: list[tuple[tuple[str, ...], Path]] = []

    def run(self, arguments, *, cwd: Path) -> None:
        values = tuple(arguments)
        self.calls.append((values, cwd))
        if values[1] == "build":
            wheel_directory = Path(values[values.index("--out-dir") + 1])
            (wheel_directory / "network_change_delivery-0.1.0-py3-none-any.whl").touch()
        elif values[1] == "export":
            output = Path(values[values.index("--output-file") + 1])
            output.write_text(
                "pydantic==2.0 --hash=sha256:" + "a" * 64,
                encoding="utf-8",
            )
        elif values[1] == "venv":
            runtime = Path(values[-1])
            (runtime / "bin").mkdir(parents=True)
            (runtime / "bin/python").touch(mode=0o700)
        elif values[1] == "pip":
            runtime = Path(values[values.index("--python") + 1]).parents[1]
            entrypoint = runtime / "bin/ncdp-protected-staging-controller"
            entrypoint.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            entrypoint.chmod(0o700)


def test_installer_copies_only_exact_private_source_set(
    tmp_path: Path, monkeypatch
) -> None:
    source = Path(__file__).parents[1]
    destination = tmp_path / "installed"
    monkeypatch.setattr(
        "network_change_delivery.protected_staging_install.verify_merged_source",
        lambda _source, _commit: None,
    )
    manifest = install_source_bundle(
        source,
        destination,
        "a" * 40,
        "personal-cml",
        "https://cml.example",
        UUID("00000000-0000-0000-0000-000000000001"),
        "https://netbox.example",
        "https://bao.example",
        "b" * 64,
        FakeRuntimeBuilder(),
        Path("/opt/protected/bin/uv"),
    )
    assert set(manifest.file_digests) == set(PROTECTED_SOURCE_FILES)
    assert (destination / "source-files.json").is_file()
    assert (destination / "runtime-files.json").is_file()
    assert (destination / "authority-manifest.json").is_file()
    assert not (destination / "tests").exists()
    assert not (destination / ".git").exists()
    assert all(
        path.stat().st_mode & 0o077 == 0
        for path in (
            destination / "source-files.json",
            destination / "runtime-files.json",
            destination / "authority-manifest.json",
        )
    )


def test_installer_refuses_checkout_destination(monkeypatch) -> None:
    source = Path(__file__).parents[1]
    monkeypatch.setattr(
        "network_change_delivery.protected_staging_install.verify_merged_source",
        lambda _source, _commit: None,
    )
    with pytest.raises(ProtectedStagingError, match="destination"):
        install_source_bundle(
            source,
            source / "installed",
            "a" * 40,
            "personal-cml",
            "https://cml.example",
            UUID("00000000-0000-0000-0000-000000000001"),
            "https://netbox.example",
            "https://bao.example",
            "b" * 64,
            FakeRuntimeBuilder(),
            Path("/opt/protected/bin/uv"),
        )


def test_controller_sources_never_execute_checkout_runtime() -> None:
    root = Path(__file__).parents[1]
    sources = "\n".join(
        (root / path).read_text(encoding="utf-8")
        for path in (
            "src/network_change_delivery/protected_staging.py",
            "src/network_change_delivery/protected_staging_controller.py",
            "src/network_change_delivery/protected_staging_install.py",
        )
    )
    for forbidden in (
        "uv run",
        "scripts/run_ephemeral_cml_staging.py",
        "scripts/buildkite/ephemeral_staging.sh",
        "sys.path.insert",
        "--terraform-root",
    ):
        assert forbidden not in sources


def test_isolated_runtime_contract_is_locked_noneditable_and_outside_source(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    bundle = tmp_path / "bundle"
    source.mkdir()
    bundle.mkdir(mode=0o700)
    runner = FakeRuntimeBuilder()
    runtime = construct_isolated_runtime(
        source, bundle, runner, uv_executable=Path("/opt/protected/bin/uv")
    )
    assert runtime == bundle / "runtime"
    commands = [call[0] for call in runner.calls]
    assert commands[0][:3] == ("/opt/protected/bin/uv", "build", "--wheel")
    assert "--frozen" in commands[1]
    assert "--no-dev" in commands[1]
    assert "--no-emit-project" in commands[1]
    assert commands[2][:4] == (
        "/opt/protected/bin/uv",
        "venv",
        "--python",
        "3.12",
    )
    assert "--require-hashes" in commands[3]
    assert "--compile-bytecode" in commands[3]
    assert "--editable" not in commands[3]
    assert str(source) not in commands[3]


def test_runtime_subprocess_runner_accepts_only_admitted_uv(
    tmp_path: Path, monkeypatch
) -> None:
    calls = []
    monkeypatch.setattr(
        "network_change_delivery.protected_staging_install.subprocess.run",
        lambda arguments, **kwargs: (
            calls.append((arguments, kwargs)) or type("Result", (), {"returncode": 0})()
        ),
    )
    runner = SubprocessRuntimeBuildRunner(
        Path("/opt/protected/bin/uv"),
        tmp_path / "cache",
        build_environment={"SDKROOT": "/opt/protected/sdk"},
    )
    runner.run(("/opt/protected/bin/uv", "build"), cwd=tmp_path)
    assert calls[0][1]["env"] == {
        "PATH": "/opt/protected/bin",
        "UV_CACHE_DIR": str(tmp_path / "cache"),
        "UV_NO_PROGRESS": "1",
        "SDKROOT": "/opt/protected/sdk",
    }
    with pytest.raises(ProtectedStagingError):
        runner.run(("/usr/bin/uv", "build"), cwd=tmp_path)
    with pytest.raises(ProtectedStagingError):
        SubprocessRuntimeBuildRunner(
            Path("/opt/protected/bin/uv"),
            tmp_path / "cache",
            build_environment={"PYTHONPATH": "/checkout"},
        )


@pytest.mark.parametrize("tamper", ["module", "entrypoint", "unexpected"])
def test_final_runtime_inventory_rejects_tamper(
    tmp_path: Path, monkeypatch, tamper: str
) -> None:
    source = Path(__file__).parents[1]
    destination = tmp_path / "installed"
    monkeypatch.setattr(
        "network_change_delivery.protected_staging_install.verify_merged_source",
        lambda _source, _commit: None,
    )
    manifest = install_source_bundle(
        source,
        destination,
        "a" * 40,
        "personal-cml",
        "https://cml.example",
        UUID("00000000-0000-0000-0000-000000000001"),
        "https://netbox.example",
        "https://bao.example",
        "b" * 64,
        FakeRuntimeBuilder(),
        Path("/opt/protected/bin/uv"),
    )
    runtime = destination / "runtime"
    if tamper == "module":
        (runtime / "bin/python").write_text("tampered", encoding="utf-8")
    elif tamper == "entrypoint":
        (runtime / "bin/ncdp-protected-staging-controller").write_text(
            "tampered", encoding="utf-8"
        )
    else:
        (runtime / "unexpected").write_text("unexpected", encoding="utf-8")
    with pytest.raises(ProtectedStagingError):
        validate_runtime_inventory(
            runtime,
            source,
            manifest,
            destination / "runtime-files.json",
        )


def test_runtime_inventory_rejects_escaping_and_entrypoint_symlinks(
    tmp_path: Path, monkeypatch
) -> None:
    source = Path(__file__).parents[1]
    destination = tmp_path / "installed"
    monkeypatch.setattr(
        "network_change_delivery.protected_staging_install.verify_merged_source",
        lambda _source, _commit: None,
    )
    manifest = install_source_bundle(
        source,
        destination,
        "a" * 40,
        "personal-cml",
        "https://cml.example",
        UUID("00000000-0000-0000-0000-000000000001"),
        "https://netbox.example",
        "https://bao.example",
        "b" * 64,
        FakeRuntimeBuilder(),
        Path("/opt/protected/bin/uv"),
    )
    entrypoint = destination / "runtime/bin/ncdp-protected-staging-controller"
    entrypoint.unlink()
    entrypoint.symlink_to("/bin/echo")
    with pytest.raises(ProtectedStagingError):
        validate_runtime_inventory(
            destination / "runtime",
            source,
            manifest,
            destination / "runtime-files.json",
        )


def test_runtime_inventory_file_tamper_is_rejected(tmp_path: Path, monkeypatch) -> None:
    source = Path(__file__).parents[1]
    destination = tmp_path / "installed"
    monkeypatch.setattr(
        "network_change_delivery.protected_staging_install.verify_merged_source",
        lambda _source, _commit: None,
    )
    manifest = install_source_bundle(
        source,
        destination,
        "a" * 40,
        "personal-cml",
        "https://cml.example",
        UUID("00000000-0000-0000-0000-000000000001"),
        "https://netbox.example",
        "https://bao.example",
        "b" * 64,
        FakeRuntimeBuilder(),
        Path("/opt/protected/bin/uv"),
    )
    inventory = destination / "runtime-files.json"
    inventory.write_text("{}", encoding="utf-8")
    with pytest.raises(ProtectedStagingError, match="inventory digest"):
        validate_runtime_inventory(destination / "runtime", source, manifest, inventory)


@pytest.mark.parametrize("artifact", ["wheel", "requirements"])
def test_retained_wheel_and_requirements_are_manifest_bound(
    tmp_path: Path, monkeypatch, artifact: str
) -> None:
    source = Path(__file__).parents[1]
    destination = tmp_path / "installed"
    monkeypatch.setattr(
        "network_change_delivery.protected_staging_install.verify_merged_source",
        lambda _source, _commit: None,
    )
    manifest = install_source_bundle(
        source,
        destination,
        "a" * 40,
        "personal-cml",
        "https://cml.example",
        UUID("00000000-0000-0000-0000-000000000001"),
        "https://netbox.example",
        "https://bao.example",
        "b" * 64,
        FakeRuntimeBuilder(),
        Path("/opt/protected/bin/uv"),
    )
    validate_runtime_artifacts(destination, manifest)
    path = (
        next((destination / "artifacts/wheels").glob("*.whl"))
        if artifact == "wheel"
        else destination / "artifacts/production-requirements.txt"
    )
    path.write_text("tampered", encoding="utf-8")
    with pytest.raises(ProtectedStagingError, match="artifacts"):
        validate_runtime_artifacts(destination, manifest)


def test_packaging_metadata_local_assets_are_in_protected_source() -> None:
    pyproject = Path(__file__).parents[1] / "pyproject.toml"
    assert 'readme = "README.md"' in pyproject.read_text(encoding="utf-8")
    assert "README.md" in PROTECTED_SOURCE_FILES


def test_actual_reduced_source_builds_immutable_protected_runtime(
    tmp_path: Path, monkeypatch
) -> None:
    source = Path(__file__).parents[1]
    uv_path = shutil.which("uv")
    if uv_path is None:
        pytest.fail("admitted uv executable is unavailable")
    destination = tmp_path / "actual-installed"
    monkeypatch.setattr(
        "network_change_delivery.protected_staging_install.verify_merged_source",
        lambda _source, _commit: None,
    )
    build_environment = {}
    if sys.platform == "darwin":
        sdk = subprocess.run(
            ["xcrun", "--show-sdk-path"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        libssh = subprocess.run(
            ["brew", "--prefix", "libssh"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        build_environment = {
            "SDKROOT": sdk,
            "CPATH": f"{libssh}/include",
            "LIBRARY_PATH": f"{libssh}/lib",
            "LDFLAGS": f"-L{libssh}/lib",
            "CPPFLAGS": f"-I{libssh}/include",
            "PKG_CONFIG_PATH": f"{libssh}/lib/pkgconfig",
        }
    manifest = install_source_bundle(
        source,
        destination,
        "a" * 40,
        "personal-cml",
        "https://cml.example",
        UUID("00000000-0000-0000-0000-000000000001"),
        "https://netbox.example",
        "https://bao.example",
        "b" * 64,
        SubprocessRuntimeBuildRunner(
            Path(uv_path),
            tmp_path / "uv-cache",
            build_environment=build_environment,
        ),
        Path(uv_path),
    )
    assert (destination / "source/README.md").is_file()
    runtime = destination / "runtime"
    inventory_path = destination / "runtime-files.json"
    before_inventory = inventory_path.read_bytes()
    before_entries, before_digest = inventory_runtime(runtime)
    entrypoint = runtime / manifest.controller_entrypoint
    result = subprocess.run(
        [str(entrypoint), "--help"],
        cwd=tmp_path,
        env={},
        check=False,
        capture_output=True,
    )
    assert result.returncode == 0
    assert b"ncdp-protected-staging-controller" in result.stdout
    after_entries, after_digest = inventory_runtime(runtime)
    assert after_entries == before_entries
    assert after_digest == before_digest
    assert inventory_path.read_bytes() == before_inventory
    validate_runtime_inventory(runtime, source, manifest, inventory_path)
    module = subprocess.run(
        [
            str(runtime / "bin/python"),
            "-c",
            (
                "import network_change_delivery.protected_staging_controller as m;"
                "print(m.__file__)"
            ),
        ],
        cwd=tmp_path,
        env={},
        check=False,
        capture_output=True,
    )
    assert module.returncode == 0
    assert str(runtime).encode() in module.stdout
    assert str(source).encode() not in module.stdout
