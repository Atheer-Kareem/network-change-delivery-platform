"""CML-anchored Oxidized host-trust boundary tests."""

from __future__ import annotations

import base64
import hashlib
import os
from datetime import UTC, datetime
from pathlib import Path

import pytest

from network_change_delivery.oxidized_controller import (
    OxidizedControlError,
    read_collection_ready,
)
from network_change_delivery.oxidized_host_trust import (
    AMBIGUITY_NAME,
    HostTrustNode,
    OxidizedHostTrustError,
    parse_known_hosts,
    publish_host_trust,
    retire_host_trust,
    validate_host_trust,
)
from network_change_delivery.oxidized_service import publish_readiness


def key(seed: bytes) -> tuple[str, str]:
    encoded = base64.b64encode(seed).decode()
    digest = base64.b64encode(hashlib.sha256(seed).digest()).decode().rstrip("=")
    return encoded, f"SHA256:{digest}"


def generation(root: Path):
    root.mkdir(mode=0o700, parents=True)
    key1, fingerprint1 = key(b"synthetic-cisco-public-key")
    key2, fingerprint2 = key(b"synthetic-junos-public-key")
    known_hosts = (
        f"192.168.4.14 ssh-rsa {key1}\n192.168.4.20 ssh-ed25519 {key2}\n"
    ).encode()
    nodes = (
        HostTrustNode(
            node="netbox-device-1",
            stable_name="core-02",
            cml_node_id="11111111-1111-1111-1111-111111111111",
            management_ip="192.168.4.14",
            algorithm="ssh-rsa",
            fingerprint=fingerprint1,
        ),
        HostTrustNode(
            node="netbox-device-2",
            stable_name="edge-junos-01",
            cml_node_id="22222222-2222-2222-2222-222222222222",
            management_ip="192.168.4.20",
            algorithm="ssh-ed25519",
            fingerprint=fingerprint2,
        ),
    )
    return known_hosts, nodes


def publish(root: Path):
    known_hosts, nodes = generation(root)
    return publish_host_trust(
        known_hosts,
        lab_id="33333333-3333-3333-3333-333333333333",
        nodes=nodes,
        root=root,
        now=datetime(2026, 8, 27, tzinfo=UTC),
    )


def test_exact_two_reviewed_hosts_are_accepted(tmp_path: Path) -> None:
    root = tmp_path / "private" / "ssh"
    metadata = publish(root)
    assert validate_host_trust(root) == metadata
    assert {item.node for item in metadata.nodes} == {
        "netbox-device-1",
        "netbox-device-2",
    }
    assert not (root / AMBIGUITY_NAME).exists()


@pytest.mark.parametrize(
    "line",
    [
        b"192.168.4.14 ssh-rsa !!!\n192.168.4.20 ssh-rsa YQ==\n",
        b"192.168.4.99 ssh-rsa YQ==\n192.168.4.20 ssh-rsa Yg==\n",
        b"192.168.4.14 ssh-rsa YQ==\n192.168.4.14 ssh-rsa Yg==\n",
        b"*.example ssh-rsa YQ==\n192.168.4.20 ssh-rsa Yg==\n",
    ],
)
def test_malformed_unexpected_duplicate_and_wildcard_hosts_rejected(
    line: bytes,
) -> None:
    with pytest.raises(OxidizedHostTrustError):
        parse_known_hosts(line)


@pytest.mark.parametrize("kind", ["relative", "symlink", "mode", "owner"])
def test_private_root_and_file_metadata_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    root = tmp_path / "private" / "ssh"
    publish(root)
    candidate = root
    if kind == "relative":
        candidate = Path("ssh")
    elif kind == "symlink":
        candidate = tmp_path / "link"
        candidate.symlink_to(root, target_is_directory=True)
    elif kind == "mode":
        (root / "known_hosts").chmod(0o640)
    else:
        monkeypatch.setattr(os, "getuid", lambda: root.stat().st_uid + 1)
    with pytest.raises(OxidizedHostTrustError):
        validate_host_trust(candidate)


def test_digest_and_metadata_mismatch_rejected(tmp_path: Path) -> None:
    root = tmp_path / "private" / "ssh"
    publish(root)
    known_hosts = root / "known_hosts"
    known_hosts.write_bytes(known_hosts.read_bytes().replace(b"Y", b"Z", 1))
    known_hosts.chmod(0o600)
    with pytest.raises(OxidizedHostTrustError):
        validate_host_trust(root)


def test_retirement_invalidates_readiness_first_and_removes_authority(
    tmp_path: Path,
) -> None:
    root = tmp_path / "private" / "ssh"
    publish(root)
    runtime = tmp_path / "runtime"
    runtime.mkdir(mode=0o700)
    readiness = runtime / "collection-ready.json"
    readiness.write_text("private marker")
    readiness.chmod(0o600)
    retire_host_trust(readiness, root)
    assert not readiness.exists()
    with pytest.raises(OxidizedHostTrustError):
        validate_host_trust(root)


def test_readiness_is_bound_to_exact_trust_digest_and_retirement(
    tmp_path: Path,
) -> None:
    root = tmp_path / "private" / "ssh"
    publish(root)
    runtime = tmp_path / "runtime"
    runtime.mkdir(mode=0o700)
    readiness = runtime / "collection-ready.json"
    publish_readiness(readiness, "a" * 64, trust_path=root)
    read_collection_ready(readiness, "a" * 64, trust_root=root)
    known_hosts = root / "known_hosts"
    known_hosts.write_bytes(known_hosts.read_bytes() + b"\n")
    known_hosts.chmod(0o600)
    with pytest.raises(OxidizedControlError):
        read_collection_ready(readiness, "a" * 64, trust_root=root)
    retire_host_trust(readiness, root)
    with pytest.raises(OxidizedControlError):
        read_collection_ready(readiness, "a" * 64, trust_root=root)


def test_cml_enrollment_is_anchored_before_fixed_keyscan() -> None:
    source = (
        Path(__file__).parents[1] / "scripts/oxidized/enroll_cml_host_trust.py"
    ).read_text()
    assert source.index("_anchor(client, lab_id, node_ids)") < source.index(
        "_scan(expected"
    )
    for contract in (
        'Path("/usr/bin/ssh-keyscan")',
        'Path("/usr/bin/ssh-keygen")',
        "title == LIVE_TITLE",
        "lab_id != LIVE_LAB",
        'node.get("state") == "BOOTED"',
        'LIVE_LAB = "09605569-0468-4fc4-8684-beb5a1342b9c"',
    ):
        assert contract in source
    for forbidden in (
        "StrictHostKeyChecking=no",
        "UserKnownHostsFile=/dev/null",
        "configuration)",
    ):
        assert forbidden not in source
