from pathlib import Path

import pytest

from network_change_delivery.protected_staging import ProtectedStagingError
from network_change_delivery.protected_staging_install import (
    PROTECTED_SOURCE_FILES,
    install_source_bundle,
)


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
    )
    assert set(manifest.file_digests) == set(PROTECTED_SOURCE_FILES)
    assert (destination / "bundle-files.json").is_file()
    assert (destination / "authority-manifest.json").is_file()
    assert not (destination / "tests").exists()
    assert not (destination / ".git").exists()
    assert all(
        path.is_dir() or path.stat().st_mode & 0o077 == 0
        for path in destination.rglob("*")
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
