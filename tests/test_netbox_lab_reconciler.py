from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from network_change_delivery.netbox_lab_reconciler import (
    EXPECTED_SERVICES,
    NETBOX_IMAGE,
    NETBOX_IMAGE_ID,
    NetBoxLabError,
    _compose,
    _private_token,
    _verify_files,
    _verify_model,
)


def test_compose_up_contract_disables_pull_and_build(tmp_path: Path) -> None:
    command = _compose(tmp_path, "up", "--detach", "--pull", "never", "--no-build")
    rendered = " ".join(command)
    assert "-p netbox-docker" in rendered
    assert f"--project-directory {tmp_path}" in rendered
    assert "up --detach --pull never --no-build" in rendered
    assert "--no-recreate" not in command


def test_file_contract_detects_change(tmp_path: Path) -> None:
    config = tmp_path / "docker-compose.yml"
    config.write_text("services: {}\n")
    config.chmod(0o600)
    contract = {"files": {config.name: hashlib.sha256(config.read_bytes()).hexdigest()}}
    _verify_files(tmp_path, contract)
    config.write_text("services:\n  unexpected: {}\n")
    with pytest.raises(NetBoxLabError, match="file contract rejected"):
        _verify_files(tmp_path, contract)


def test_authority_token_must_be_private_regular_file(tmp_path: Path) -> None:
    token = tmp_path / "netbox-token"
    token.write_text("not-a-real-token")
    token.chmod(0o600)
    assert _private_token(token) == "not-a-real-token"
    token.chmod(0o644)
    with pytest.raises(NetBoxLabError, match="authority rejected"):
        _private_token(token)


def test_model_requires_exact_service_and_image_population(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    responses = iter(
        [
            "\n".join(EXPECTED_SERVICES),
            "\n".join(
                [
                    NETBOX_IMAGE,
                    NETBOX_IMAGE,
                    "docker.io/postgres:18-alpine",
                    "docker.io/valkey/valkey:9.1-alpine",
                    "docker.io/valkey/valkey:9.1-alpine",
                ]
            ),
        ]
    )
    monkeypatch.setattr(
        "network_change_delivery.netbox_lab_reconciler._run",
        lambda *_args, **_kwargs: next(responses),
    )
    _verify_model(
        tmp_path,
        {
            "service_images": sorted(
                [
                    NETBOX_IMAGE,
                    NETBOX_IMAGE,
                    "docker.io/postgres:18-alpine",
                    "docker.io/valkey/valkey:9.1-alpine",
                    "docker.io/valkey/valkey:9.1-alpine",
                ]
            )
        },
    )


def test_source_contains_exact_image_and_no_destructive_compose() -> None:
    source = (
        Path(__file__).parents[1]
        / "src/network_change_delivery/netbox_lab_reconciler.py"
    ).read_text()
    assert NETBOX_IMAGE_ID in source
    assert '"--pull", "never", "--no-build"' in source
    assert '"down"' not in source
    assert '"volume", "rm"' not in source
    assert '"pull"' not in source.replace('"--pull"', "")
    assert "allow_legacy_location=True" in source
    assert "allow_absent=True" in source
