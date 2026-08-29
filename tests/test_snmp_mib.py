from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from network_change_delivery.snmp_mib import (
    APPROVED_DEVICE_VIEW_OIDS,
    APPROVED_GET_OIDS,
    APPROVED_METRIC_OIDS,
    APPROVED_WALK_OIDS,
    EXPORTER_IMAGE,
    EXPORTER_VERSION,
    SnmpMibContractError,
    validate_device_view_oids,
    validate_generated_module,
)

ROOT = Path(__file__).parents[1]
GENERATOR = ROOT / "infrastructure/observability/snmp/generator.yml"
GENERATED = ROOT / "infrastructure/observability/snmp/snmp-modules.yml"


def generated_payload() -> dict[str, object]:
    return yaml.safe_load(GENERATED.read_text())


def test_generated_module_has_exact_reviewed_oid_closure() -> None:
    content = GENERATED.read_bytes()
    validate_generated_module(content)
    module = generated_payload()["modules"]["ncdp_if_mib"]
    assert set(module["get"]) == APPROVED_GET_OIDS
    assert set(module["walk"]) == APPROVED_WALK_OIDS
    assert {item["name"]: item["oid"] for item in module["metrics"]} == (
        APPROVED_METRIC_OIDS
    )
    assert not {"ifInOctets", "ifOutOctets"} & set(APPROVED_METRIC_OIDS)
    assert EXPORTER_VERSION == "0.30.1"
    assert EXPORTER_IMAGE.endswith(
        "sha256:e5fd5e8b43ace6c088fe9bf0b37b7fff0e04380bee352be7ec41b853a4dd5859"
    )


def test_generator_source_is_module_only_and_has_no_auths() -> None:
    source = yaml.safe_load(GENERATOR.read_text())
    assert set(source) == {"modules"}
    assert set(source["modules"]) == {"ncdp_if_mib"}
    serialized = GENERATOR.read_text().casefold()
    for forbidden in ("auths:", "community:", "password", "priv_password"):
        assert forbidden not in serialized


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value.update({"auths": {"bad": {"version": 2}}}),
        lambda value: value["modules"]["ncdp_if_mib"]["walk"].append("1.3.6.1.2.1.2"),
        lambda value: value["modules"]["ncdp_if_mib"]["metrics"].append(
            {
                "name": "ifInOctets",
                "oid": "1.3.6.1.2.1.2.2.1.10",
                "type": "counter",
            }
        ),
        lambda value: value["modules"]["ncdp_if_mib"]["metrics"][2].pop("lookups"),
    ],
)
def test_generated_authority_expansion_fails_closed(mutation) -> None:
    payload = generated_payload()
    mutation(payload)
    with pytest.raises(SnmpMibContractError):
        validate_generated_module(yaml.safe_dump(payload))


def test_future_device_view_must_equal_generated_oid_closure() -> None:
    validate_device_view_oids(APPROVED_DEVICE_VIEW_OIDS)
    with pytest.raises(SnmpMibContractError, match="view closure"):
        validate_device_view_oids(APPROVED_DEVICE_VIEW_OIDS | {"1.3.6.1.2.1.2"})
    with pytest.raises(SnmpMibContractError, match="view closure"):
        validate_device_view_oids(
            APPROVED_DEVICE_VIEW_OIDS - {"1.3.6.1.2.1.31.1.1.1.1"}
        )
