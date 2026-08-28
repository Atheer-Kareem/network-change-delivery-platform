import hashlib
import json
import subprocess
import venv
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


def test_retained_wheel_and_requirements_are_manifest_bound(
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
    validate_runtime_artifacts(destination, manifest)
    wheel = next((destination / "artifacts/wheels").glob("*.whl"))
    wheel.write_text("tampered", encoding="utf-8")
    with pytest.raises(ProtectedStagingError, match="artifacts"):
        validate_runtime_artifacts(destination, manifest)


def test_real_temporary_runtime_validates_and_executes_without_checkout(
    tmp_path: Path, monkeypatch
) -> None:
    source = Path(__file__).parents[1]
    destination = tmp_path / "installed"
    monkeypatch.setattr(
        "network_change_delivery.protected_staging_install.verify_merged_source",
        lambda _source, _commit: None,
    )
    base = install_source_bundle(
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
    runtime = destination / "runtime-real"
    venv.EnvBuilder(with_pip=False, symlinks=False).create(runtime)
    runtime.chmod(0o700)
    entrypoint = runtime / "bin/ncdp-protected-staging-controller"
    entrypoint.write_text(
        '#!/bin/sh\nexec "$(dirname "$0")/python" --version\n', encoding="utf-8"
    )
    entrypoint.chmod(0o700)
    entries, digest = inventory_runtime(runtime)
    raw = json.dumps(entries, sort_keys=True, separators=(",", ":")).encode()
    inventory = destination / "runtime-real-files.json"
    inventory.write_bytes(raw)
    inventory.chmod(0o600)
    manifest = base.model_copy(
        update={
            "runtime_inventory_sha256": hashlib.sha256(raw).hexdigest(),
            "runtime_digest": digest,
        }
    )
    validate_runtime_inventory(runtime, source, manifest, inventory)
    result = subprocess.run(
        [str(entrypoint)], cwd=tmp_path, env={}, check=False, capture_output=True
    )
    assert result.returncode == 0
    assert b"Python 3.12" in result.stdout
