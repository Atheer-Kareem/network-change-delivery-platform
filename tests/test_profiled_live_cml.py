"""Bounded persistent profiled CML operator tests."""

from __future__ import annotations

import inspect
from pathlib import Path

import httpx
import pytest

from network_change_delivery.profiled_live_cml import (
    ACCESS_NODE_ID,
    CORE_NODE_ID,
    JUNOS_NODE_ID,
    LIVE_LAB_ID,
    NEW_NODE_SPECS,
    TRANSIT_NODE_ID,
    ProfiledLiveCmlError,
    ProfiledLiveCmlOperator,
    ios_scrypt_password_hash,
    render_ios_bootstrap,
)

ROOT = Path(__file__).parents[1]


def test_exact_new_node_profile_contract_is_frozen() -> None:
    assert tuple(
        (
            item.logical_name,
            item.device_id,
            item.accepted_node_id,
            item.node_definition,
            item.image_definition,
            item.management_address,
        )
        for item in NEW_NODE_SPECS
    ) == (
        (
            "transit-ios-01",
            8,
            TRANSIT_NODE_ID,
            "iosv",
            "iosv-159-3-m12",
            "192.168.4.16",
        ),
        (
            "access-sw-01",
            9,
            ACCESS_NODE_ID,
            "iosvl2",
            "iosvl2-2020",
            "192.168.4.17",
        ),
    )
    assert LIVE_LAB_ID == "09605569-0468-4fc4-8684-beb5a1342b9c"
    assert CORE_NODE_ID == "59fc118d-dfa3-4a45-a905-6a056b591550"
    assert JUNOS_NODE_ID == "3ee87d9c-09b5-4ed2-a655-092bf89b1190"
    assert TRANSIT_NODE_ID == "b6a5e482-a867-4b88-addc-02eb068afb84"
    assert ACCESS_NODE_ID == "fee01570-a8c6-478c-9e29-ebb991335346"


def test_accepted_profiled_node_identity_cannot_be_silently_recreated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spec = NEW_NODE_SPECS[0]
    operator = ProfiledLiveCmlOperator(
        httpx.Client(base_url="https://cml.invalid", trust_env=False)
    )
    monkeypatch.setattr(operator, "_node", lambda _node_id: {"label": spec.label})
    with pytest.raises(ProfiledLiveCmlError, match="identity conflicts"):
        operator._admit_node(
            spec,
            "hostname transit-ios-01\n",
            ["33333333-3333-4333-8333-333333333333"],
        )
    with pytest.raises(ProfiledLiveCmlError, match="missing"):
        operator._admit_node(spec, "hostname transit-ios-01\n", [])

    with pytest.raises(ProfiledLiveCmlError, match="identity rejected"):
        operator.anchor_profiled_live(
            transit_node_id="33333333-3333-4333-8333-333333333333",
            access_node_id=ACCESS_NODE_ID,
        )


def test_extracted_bootstrap_must_retain_the_exact_openbao_derived_verifier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spec = NEW_NODE_SPECS[0]
    operator = ProfiledLiveCmlOperator(
        httpx.Client(base_url="https://cml.invalid", trust_env=False)
    )
    expected = render_ios_bootstrap(
        spec,
        username="netdevops",
        password_hash=ios_scrypt_password_hash(
            "synthetic-B3-password-123", spec.password_salt
        ),
    )
    node = {
        "label": spec.label,
        "node_definition": spec.node_definition,
        "image_definition": spec.image_definition,
    }
    monkeypatch.setattr(operator, "_node", lambda _node_id: node)
    wrong = expected.replace(
        "$9$ncdpd08B34salt$bJ53.hOqB1Sel7FxjtUYjNW/Jvh2e.9QIu/e5ifbLN6",
        "$9$ncdpd08B34salt$AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
    )
    monkeypatch.setattr(operator, "_configuration", lambda _node_id: wrong)
    with pytest.raises(ProfiledLiveCmlError, match="bootstrap conflicts"):
        operator._admit_node(
            spec,
            expected,
            [spec.accepted_node_id],
        )


def test_hashed_bootstrap_never_contains_plaintext_password() -> None:
    password = "bounded-synthetic-password-123456789"
    for spec in NEW_NODE_SPECS:
        verifier = ios_scrypt_password_hash(password, spec.password_salt)
        configuration = render_ios_bootstrap(
            spec, username="netdevops", password_hash=verifier
        )
        assert password not in configuration
        assert "platform console serial" not in configuration
        assert "secret 0" not in configuration
        assert "secret 5" not in configuration
        assert f"secret 9 {verifier}" in configuration
        assert f"hostname {spec.logical_name}" in configuration
        assert f"ip address {spec.management_address} 255.255.255.0" in configuration
        assert "crypto key generate rsa modulus 2048" in configuration
        assert "transport input ssh" in configuration
    switch = render_ios_bootstrap(
        NEW_NODE_SPECS[1],
        username="netdevops",
        password_hash=ios_scrypt_password_hash(password, "ncdpd09B34salt"),
    )
    assert "interface GigabitEthernet0/0\n no switchport" in switch


def test_ios_type9_verifier_is_deterministic_and_strictly_bounded() -> None:
    assert (
        ios_scrypt_password_hash("synthetic-B3-password-123", "ncdpd08B34salt")
        == "$9$ncdpd08B34salt$bJ53.hOqB1Sel7FxjtUYjNW/Jvh2e.9QIu/e5ifbLN6"
    )
    for password in ("", "contains whitespace", 'contains"quote', "x" * 128):
        with pytest.raises(ProfiledLiveCmlError, match="password"):
            ios_scrypt_password_hash(password, "ncdpd08B34salt")
    for salt in ("short", "ncdpd08B34sal!", "ncdpd08B34saltx"):
        with pytest.raises(ProfiledLiveCmlError, match="salt"):
            ios_scrypt_password_hash("synthetic-password", salt)


def test_link_reconciliation_reuses_exact_and_rejects_occupied_endpoint() -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(201, json="33333333-3333-4333-8333-333333333333")

    client = httpx.Client(
        base_url="https://cml.invalid",
        transport=httpx.MockTransport(handler),
        trust_env=False,
    )
    operator = ProfiledLiveCmlOperator(client)
    existing = {frozenset(("a", "b")): "existing"}
    assert operator._ensure_link("a", "b", existing) == ("existing", False)
    assert not calls
    with pytest.raises(ProfiledLiveCmlError, match="occupied"):
        operator._ensure_link("a", "c", existing)
    assert not calls
    assert operator._ensure_link("c", "d", existing) == (
        "33333333-3333-4333-8333-333333333333",
        True,
    )
    assert calls[0].method == "POST"
    assert calls[0].url.path == f"/api/v0/labs/{LIVE_LAB_ID}/links"


def test_stored_bootstrap_accepts_installed_single_file_response_shape() -> None:
    node_id = "33333333-3333-4333-8333-333333333333"

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/configuration") or request.url.path.endswith(
            "/configurations"
        ):
            return httpx.Response(404, json={"detail": "absent"})
        return httpx.Response(
            200,
            json={
                "configuration": [
                    {"name": "ios_config.txt", "content": "hostname synthetic\n"}
                ]
            },
        )

    client = httpx.Client(
        base_url="https://cml.invalid",
        transport=httpx.MockTransport(handler),
        trust_env=False,
    )
    operator = ProfiledLiveCmlOperator(client)
    assert operator._configuration(node_id) == "hostname synthetic\n"


def test_rebootstrap_uses_whole_lab_stop_edit_wipe_start_sequence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    node_id = "33333333-3333-4333-8333-333333333333"
    operator = ProfiledLiveCmlOperator(
        httpx.Client(base_url="https://cml.invalid", trust_env=False)
    )
    calls: list[tuple[str, str, dict[str, object] | None]] = []
    states = iter(({"state": "STARTED"}, {"state": "STOPPED"}))
    monkeypatch.setattr(operator, "_get", lambda _path: next(states))

    def request(method, path, *, json=None, expected=(200,)):
        del expected
        calls.append((method, path, json))

    monkeypatch.setattr(
        operator,
        "_request",
        request,
    )
    operator._rebootstrap_new_nodes({node_id: "hostname synthetic\n"})
    assert [item[0] for item in calls] == ["PUT", "PUT", "PATCH", "PUT"]
    assert calls[0][1] == f"/api/v0/labs/{LIVE_LAB_ID}/stop"
    assert calls[1][1].endswith("/wipe_disks")
    assert calls[2][2] == {
        "configuration": [{"name": "ios_config.txt", "content": "hostname synthetic\n"}]
    }
    assert calls[3][1] == f"/api/v0/labs/{LIVE_LAB_ID}/start"


def test_rebootstrap_resumes_from_independently_proven_stopped_lab(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    node_id = "33333333-3333-4333-8333-333333333333"
    operator = ProfiledLiveCmlOperator(
        httpx.Client(base_url="https://cml.invalid", trust_env=False)
    )
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(operator, "_get", lambda _path: {"state": "STOPPED"})

    def request(method, path, *, json=None, expected=(200,)):
        del json, expected
        calls.append((method, path))

    monkeypatch.setattr(operator, "_request", request)
    operator._rebootstrap_new_nodes({node_id: "hostname synthetic\n"})
    assert calls == [
        ("PUT", f"/api/v0/labs/{LIVE_LAB_ID}/nodes/{node_id}/wipe_disks"),
        ("PATCH", f"/api/v0/labs/{LIVE_LAB_ID}/nodes/{node_id}"),
        ("PUT", f"/api/v0/labs/{LIVE_LAB_ID}/start"),
    ]


def test_rebootstrap_rejects_baseline_nodes() -> None:
    operator = ProfiledLiveCmlOperator(
        httpx.Client(base_url="https://cml.invalid", trust_env=False)
    )
    with pytest.raises(ProfiledLiveCmlError, match="baseline"):
        operator._rebootstrap_new_nodes({CORE_NODE_ID: "hostname forbidden\n"})


def test_operator_scope_has_no_delete_terraform_or_device_write_path() -> None:
    source = inspect.getsource(ProfiledLiveCmlOperator)
    assert '"DELETE"' not in source
    assert "terraform" not in source.casefold()
    script = (ROOT / "scripts/cml/realize_profiled_live.py").read_text()
    assert "password}" not in script
    assert "bootstrap credential values: REDACTED" in script
    assert "StrictHostKeyChecking=no" not in script
    assert "AutoAddPolicy" not in script
