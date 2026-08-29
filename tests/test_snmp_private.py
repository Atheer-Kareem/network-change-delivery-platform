from __future__ import annotations

import os
import secrets
from pathlib import Path

import pytest
import yaml

from network_change_delivery.snmp_private import (
    AMBIGUITY_GUARD,
    AUTH_FILENAME,
    SnmpPrivatePublicationError,
    publish_snmp_auth,
    validate_published_snmp_auth,
)

_TEST_CREDENTIALS = {
    generation: {
        "username": f"synthetic_{generation}_{secrets.token_hex(4)}",
        "password": f"auth_{secrets.token_hex(16)}",
        "privacy": f"privacy_{secrets.token_hex(16)}",
    }
    for generation in ("a", "b")
}


def auth_content(generation: str) -> bytes:
    credential = _TEST_CREDENTIALS[generation]
    return yaml.safe_dump(
        {
            "auths": {
                f"ncdp_device_1_{generation}": {
                    "version": 3,
                    "security_level": "authPriv",
                    "username": credential["username"],
                    "password": credential["password"],
                    "auth_protocol": "SHA256",
                    "priv_protocol": "AES",
                    "priv_password": credential["privacy"],
                }
            }
        },
        sort_keys=True,
    ).encode()


def test_auth_publication_is_private_atomic_and_rotates_in_same_directory(
    tmp_path: Path,
) -> None:
    root = tmp_path / "external" / "snmp-auth"
    first = publish_snmp_auth(root, auth_content("a"))
    first_inode = first.stat().st_ino
    assert root.stat().st_mode & 0o777 == 0o700
    assert first.stat().st_mode & 0o777 == 0o600
    assert first.stat().st_nlink == 1
    second = publish_snmp_auth(root, auth_content("b"))
    assert second == first
    assert second.stat().st_ino != first_inode
    assert validate_published_snmp_auth(root) == auth_content("b")
    assert not (root / AMBIGUITY_GUARD).exists()


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value.update({"modules": {}}),
        lambda value: value["auths"]["ncdp_device_1_a"].update(
            {"security_level": "authNoPriv"}
        ),
        lambda value: value["auths"]["ncdp_device_1_a"].update(
            {"auth_protocol": "SHA"}
        ),
        lambda value: value["auths"]["ncdp_device_1_a"].update(
            {"priv_protocol": "DES"}
        ),
        lambda value: value["auths"]["ncdp_device_1_a"].update({"community": "public"}),
    ],
)
def test_invalid_auth_replacement_fails_before_changing_active_file(
    tmp_path: Path, mutation
) -> None:
    root = tmp_path / "external" / "snmp-auth"
    original = auth_content("a")
    publish_snmp_auth(root, original)
    invalid = yaml.safe_load(original)
    mutation(invalid)
    with pytest.raises(SnmpPrivatePublicationError, match="rejected"):
        publish_snmp_auth(root, yaml.safe_dump(invalid).encode())
    assert validate_published_snmp_auth(root) == original


def test_auth_publication_rejects_symlink_hardlink_mode_and_guard(
    tmp_path: Path,
) -> None:
    root = tmp_path / "external" / "snmp-auth"
    publish_snmp_auth(root, auth_content("a"))
    active = root / AUTH_FILENAME
    active.unlink()
    outside = tmp_path / "outside"
    outside.write_bytes(auth_content("a"))
    outside.chmod(0o600)
    active.symlink_to(outside)
    with pytest.raises(SnmpPrivatePublicationError, match="path rejected"):
        publish_snmp_auth(root, auth_content("b"))
    active.unlink()
    os.link(outside, active)
    with pytest.raises(SnmpPrivatePublicationError, match="path rejected"):
        publish_snmp_auth(root, auth_content("b"))
    active.unlink()
    active.write_bytes(auth_content("a"))
    active.chmod(0o644)
    with pytest.raises(SnmpPrivatePublicationError, match="path rejected"):
        publish_snmp_auth(root, auth_content("b"))
    active.chmod(0o600)
    guard = root / AMBIGUITY_GUARD
    guard.write_text("AMBIGUOUS\n")
    guard.chmod(0o600)
    with pytest.raises(SnmpPrivatePublicationError, match="ambiguous"):
        validate_published_snmp_auth(root)


def test_auth_publication_failure_leaves_guard_for_fail_closed_recovery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "external" / "snmp-auth"
    publish_snmp_auth(root, auth_content("a"))
    original_replace = Path.replace

    def fail_active_replace(path: Path, target: Path):
        if Path(target).name == AUTH_FILENAME:
            raise OSError("synthetic failure")
        return original_replace(path, target)

    monkeypatch.setattr(Path, "replace", fail_active_replace)
    with pytest.raises(SnmpPrivatePublicationError, match="publication failed"):
        publish_snmp_auth(root, auth_content("b"))
    assert (root / AMBIGUITY_GUARD).exists()
    assert (root / AUTH_FILENAME).read_bytes() == auth_content("a")
