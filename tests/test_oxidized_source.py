from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from types import SimpleNamespace

import pytest

from network_change_delivery.architecture_contracts import (
    AutomationProfileID,
    NetworkOS,
)
from network_change_delivery.inventory import InventoryError
from network_change_delivery.oxidized_source import (
    OxidizedSourceError,
    OxidizedSourcePublicationAmbiguousError,
    materialize_oxidized_source,
)
from network_change_delivery.secrets import (
    CredentialReference,
    DeviceCredentials,
    SecretError,
)


class Device:
    def __init__(
        self,
        device_id: int,
        profile: AutomationProfileID,
        host: str,
        *,
        identity: str | None = None,
        logical_name: str | None = None,
        platform_slug: str | None = None,
        network_os: NetworkOS | None = None,
    ):
        self.device_identity = identity or f"netbox:dcim.device:{device_id}"
        self.host = host
        self.logical_name = logical_name or {
            1: "core-02",
            2: "edge-junos-01",
            8: "transit-ios-01",
            9: "access-sw-01",
        }.get(device_id, f"unknown-{device_id}")
        self.platform = SimpleNamespace(
            slug=platform_slug
            or {
                AutomationProfileID.CAT8000V_IOSXE: "cisco-ios-xe",
                AutomationProfileID.VJUNOS_ROUTER: "juniper-junos",
                AutomationProfileID.IOSV_159_3_M12: "cisco-ios",
                AutomationProfileID.IOSVL2_2020: "cisco-ios",
            }.get(profile, "unknown-platform")
        )
        self.network_os = network_os or {
            AutomationProfileID.CAT8000V_IOSXE: NetworkOS.IOSXE,
            AutomationProfileID.VJUNOS_ROUTER: NetworkOS.JUNOS,
            AutomationProfileID.IOSV_159_3_M12: NetworkOS.IOS,
            AutomationProfileID.IOSVL2_2020: NetworkOS.IOS,
        }.get(profile, "unknown-nos")
        self.automation_profile_id = profile

    def live_read_only_target(self):
        return SimpleNamespace(host=self.host)


def device(device_id: int, profile: AutomationProfileID, *, host: str) -> Device:
    return Device(device_id, profile, host)


DEVICES = (
    device(1, AutomationProfileID.CAT8000V_IOSXE, host="192.0.2.1"),
    device(2, AutomationProfileID.VJUNOS_ROUTER, host="192.0.2.2"),
    device(8, AutomationProfileID.IOSV_159_3_M12, host="192.0.2.8"),
    device(9, AutomationProfileID.IOSVL2_2020, host="192.0.2.9"),
)


class Inventory:
    def __init__(self, devices=DEVICES, error: Exception | None = None) -> None:
        self.devices = devices
        self.error = error

    def resolve_profiled_population(self):
        if self.error:
            raise self.error
        return SimpleNamespace(devices=self.devices)


class Secrets:
    def __init__(self, *, fail_id: int | None = None, source: str = "openbao") -> None:
        self.fail_id = fail_id
        self.source = source

    def reference(self, target: Device) -> CredentialReference:
        device_id = int(target.device_identity.rsplit(":", 1)[1])
        reference = f"openbao:kv-v2:ncdp/devices/{device_id}/ssh"
        return CredentialReference(self.source, reference)  # type: ignore[arg-type]

    def load(self, target: Device) -> DeviceCredentials:
        device_id = int(target.device_identity.rsplit(":", 1)[1])
        if device_id == self.fail_id:
            raise SecretError("bounded failure")
        return DeviceCredentials(
            username=f"private-user-{device_id}", password=f"private-pass-{device_id}"
        )


def test_exact_population_maps_deterministically_and_forces_ssh_22(
    tmp_path: Path,
) -> None:
    root = tmp_path / "oxidized"
    result = materialize_oxidized_source(Inventory(DEVICES[::-1]), Secrets(), root)
    payload = json.loads(result.path.read_text())
    assert result.identities == tuple(f"netbox:dcim.device:{i}" for i in (1, 2, 8, 9))
    assert result.node_names == tuple(f"netbox-device-{i}" for i in (1, 2, 8, 9))
    assert result.changed is True
    assert [(node["name"], node["model"], node["ssh_port"]) for node in payload] == [
        ("netbox-device-1", "ios", 22),
        ("netbox-device-2", "junos", 22),
        ("netbox-device-8", "ios", 22),
        ("netbox-device-9", "ios", 22),
    ]
    assert all(node["group"] == "managed" for node in payload)
    assert all(
        set(node)
        == {"name", "ip", "model", "group", "username", "password", "ssh_port"}
        for node in payload
    )
    assert stat.S_IMODE(root.stat().st_mode) == 0o700
    assert stat.S_IMODE((root / "runtime").stat().st_mode) == 0o700
    assert stat.S_IMODE(result.path.stat().st_mode) == 0o600
    assert result.path.stat().st_uid == os.getuid()


def test_identical_source_is_not_republished(tmp_path: Path) -> None:
    root = tmp_path / "oxidized"
    first = materialize_oxidized_source(Inventory(), Secrets(), root)
    inode = first.path.stat().st_ino
    second = materialize_oxidized_source(Inventory(), Secrets(), root)
    assert second.changed is False
    assert second.path.stat().st_ino == inode


@pytest.mark.parametrize(
    "population",
    [
        (),
        (DEVICES[0],),
        (DEVICES[1],),
        (
            *DEVICES,
            device(3, AutomationProfileID.VJUNOS_ROUTER, host="192.0.2.3"),
        ),
    ],
)
def test_population_must_be_exact(population) -> None:
    with pytest.raises(OxidizedSourceError, match="population"):
        materialize_oxidized_source(Inventory(population), Secrets(), Path("/tmp/x"))


def test_duplicate_identity_is_rejected() -> None:
    with pytest.raises(OxidizedSourceError, match="population"):
        materialize_oxidized_source(
            Inventory((DEVICES[0], DEVICES[0])), Secrets(), Path("/tmp/x")
        )


@pytest.mark.parametrize(
    "candidate",
    [
        Device(1, AutomationProfileID.IOSVL2_2020, "192.0.2.1"),
        Device(
            9,
            AutomationProfileID.IOSVL2_2020,
            "192.0.2.9",
            identity="netbox:dcim.device:8",
        ),
        Device(
            1,
            AutomationProfileID.CAT8000V_IOSXE,
            "192.0.2.1",
            platform_slug="cisco-ios",
        ),
    ],
)
def test_consumer_subject_admission_rejects_mismatched_profiled_subject(
    candidate: Device, tmp_path: Path
) -> None:
    population = (
        (candidate, DEVICES[0], DEVICES[1], DEVICES[3])
        if candidate.device_identity.endswith(":8")
        else (candidate, *DEVICES[1:])
    )
    with pytest.raises(OxidizedSourceError, match="profiled subject"):
        materialize_oxidized_source(Inventory(population), Secrets(), tmp_path / "o")


def test_unsupported_oxidized_profile_fails_closed(tmp_path: Path) -> None:
    candidate = Device(1, "unsupported-profile", "192.0.2.1")  # type: ignore[arg-type]
    with pytest.raises(OxidizedSourceError, match="profiled subject"):
        materialize_oxidized_source(
            Inventory((candidate, *DEVICES[1:])), Secrets(), tmp_path / "o"
        )


def test_non_openbao_reference_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(OxidizedSourceError, match="reference rejected"):
        materialize_oxidized_source(
            Inventory(), Secrets(source="environment"), tmp_path / "o"
        )


def test_invalid_ipv4_is_rejected_before_publication(tmp_path: Path) -> None:
    invalid = Device(1, AutomationProfileID.CAT8000V_IOSXE, "not-an-ipv4-address")
    with pytest.raises(OxidizedSourceError, match="credential loading"):
        materialize_oxidized_source(
            Inventory((invalid, *DEVICES[1:])), Secrets(), tmp_path / "oxidized"
        )
    assert not (tmp_path / "oxidized").exists()


def test_failure_before_publication_preserves_existing_source(tmp_path: Path) -> None:
    root = tmp_path / "oxidized"
    path = materialize_oxidized_source(Inventory(), Secrets(), root).path
    previous = path.read_bytes()
    with pytest.raises(OxidizedSourceError, match="credential loading"):
        materialize_oxidized_source(Inventory(), Secrets(fail_id=2), root)
    assert path.read_bytes() == previous
    assert not list(path.parent.glob(".router.json.tmp-*"))


def test_temporary_fsync_failure_preserves_existing_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "oxidized"
    path = materialize_oxidized_source(Inventory(), Secrets(), root).path
    previous = path.read_bytes()
    monkeypatch.setattr(
        "network_change_delivery.oxidized_source._existing_payload_matches",
        lambda *_args: False,
    )

    def fail_fsync(_descriptor: int) -> None:
        raise OSError("injected")

    monkeypatch.setattr(os, "fsync", fail_fsync)
    with pytest.raises(OxidizedSourceError, match="publication failed"):
        materialize_oxidized_source(Inventory(), Secrets(), root)
    assert path.read_bytes() == previous
    assert not list(path.parent.glob(".router.json.tmp-*"))


def test_replace_failure_preserves_existing_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "oxidized"
    path = materialize_oxidized_source(Inventory(), Secrets(), root).path
    previous = path.read_bytes()
    monkeypatch.setattr(
        "network_change_delivery.oxidized_source._existing_payload_matches",
        lambda *_args: False,
    )

    def fail_replace(_source: Path, _target: Path) -> Path:
        raise OSError("injected")

    monkeypatch.setattr(Path, "replace", fail_replace)
    with pytest.raises(OxidizedSourceError, match="publication failed"):
        materialize_oxidized_source(Inventory(), Secrets(), root)
    assert path.read_bytes() == previous
    assert not list(path.parent.glob(".router.json.tmp-*"))


def test_directory_fsync_failure_is_post_commit_ambiguous(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "oxidized"
    path = materialize_oxidized_source(Inventory(), Secrets(), root).path
    path.write_bytes(b"previous-source\n")
    calls = 0
    real_fsync = os.fsync

    def fail_second_fsync(descriptor: int) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("injected")
        real_fsync(descriptor)

    monkeypatch.setattr(os, "fsync", fail_second_fsync)
    with pytest.raises(
        OxidizedSourcePublicationAmbiguousError,
        match=r"^Oxidized source publication outcome ambiguous$",
    ):
        materialize_oxidized_source(Inventory(), Secrets(), root)
    assert path.read_bytes() != b"previous-source\n"
    assert not list(path.parent.glob(".router.json.tmp-*"))


def test_symlink_root_and_checkout_root_are_rejected(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir(mode=0o700)
    link = tmp_path / "link"
    link.symlink_to(target, target_is_directory=True)
    with pytest.raises(OxidizedSourceError, match="directory rejected"):
        materialize_oxidized_source(Inventory(), Secrets(), link)
    checkout = Path(__file__).parents[1] / "forbidden-oxidized"
    with pytest.raises(OxidizedSourceError, match="root rejected"):
        materialize_oxidized_source(Inventory(), Secrets(), checkout)


def test_audit_store_root_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(OxidizedSourceError, match="root rejected"):
        materialize_oxidized_source(Inventory(), Secrets(), tmp_path / "audit")


def test_operator_script_uses_only_dedicated_authority_variables() -> None:
    script = (
        Path(__file__).parents[1] / "scripts/oxidized/materialize_source.py"
    ).read_text()
    for name in (
        "NCDP_OXIDIZED_NETBOX_URL",
        "NCDP_OXIDIZED_NETBOX_TOKEN",
        "NCDP_OXIDIZED_OPENBAO_URL",
        "NCDP_OXIDIZED_OPENBAO_ROLE_ID",
        "NCDP_OXIDIZED_OPENBAO_SECRET_ID",
        "NCDP_OXIDIZED_RUNTIME_ROOT",
    ):
        assert name in script
    for forbidden in (
        "NCDP_DEVICE_USERNAME",
        "NCDP_DEVICE_PASSWORD",
        "BUILDKITE_AGENT_ACCESS_TOKEN",
    ):
        assert forbidden not in script


def test_jsonfile_verifier_checks_private_source_metadata_before_docker() -> None:
    script = (
        Path(__file__).parents[1] / "scripts/oxidized/verify_jsonfile_source.sh"
    ).read_text()
    metadata_check = script.index("metadata = os.lstat")
    docker_start = script.index("container=$(docker run")
    assert metadata_check < docker_start
    for contract in (
        "stat.S_ISREG",
        "stat.S_ISLNK",
        "metadata.st_uid == os.getuid()",
        "stat.S_IMODE(metadata.st_mode) == 0o600",
        "metadata.st_nlink == 1",
    ):
        assert contract in script


def test_errors_and_reprs_do_not_expose_credentials(tmp_path: Path) -> None:
    credentials = DeviceCredentials("highly-private-user", "highly-private-password")
    assert "highly-private" not in repr(credentials)
    with pytest.raises(OxidizedSourceError) as caught:
        materialize_oxidized_source(
            Inventory(error=InventoryError("raw-private-response")),
            Secrets(),
            tmp_path / "oxidized",
        )
    assert "raw-private-response" not in str(caught.value)
