"""Reviewed SNMP exporter module and exact device-view OID closure."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Final

import yaml

MODULE_NAME: Final = "ncdp_if_mib"
EXPORTER_VERSION: Final = "0.30.1"
EXPORTER_IMAGE: Final = (
    "prom/snmp-exporter:v0.30.1@"
    "sha256:e5fd5e8b43ace6c088fe9bf0b37b7fff0e04380bee352be7ec41b853a4dd5859"
)

APPROVED_GET_OIDS: Final = frozenset(
    {
        "1.3.6.1.2.1.1.3.0",  # sysUpTime.0
        "1.3.6.1.2.1.2.1.0",  # ifNumber.0
        "1.3.6.1.2.1.31.1.5.0",  # ifTableLastChange.0
    }
)
APPROVED_WALK_OIDS: Final = frozenset(
    {
        "1.3.6.1.2.1.2.2.1.1",  # ifIndex
        "1.3.6.1.2.1.2.2.1.7",  # ifAdminStatus
        "1.3.6.1.2.1.2.2.1.8",  # ifOperStatus
        "1.3.6.1.2.1.2.2.1.13",  # ifInDiscards
        "1.3.6.1.2.1.2.2.1.14",  # ifInErrors
        "1.3.6.1.2.1.2.2.1.19",  # ifOutDiscards
        "1.3.6.1.2.1.2.2.1.20",  # ifOutErrors
        "1.3.6.1.2.1.31.1.1.1.1",  # ifName
        "1.3.6.1.2.1.31.1.1.1.6",  # ifHCInOctets
        "1.3.6.1.2.1.31.1.1.1.10",  # ifHCOutOctets
        "1.3.6.1.2.1.31.1.1.1.15",  # ifHighSpeed
        "1.3.6.1.2.1.31.1.1.1.19",  # ifCounterDiscontinuityTime
    }
)
APPROVED_METRIC_OIDS: Final = {
    "sysUpTime": "1.3.6.1.2.1.1.3",
    "ifNumber": "1.3.6.1.2.1.2.1",
    "ifIndex": "1.3.6.1.2.1.2.2.1.1",
    "ifAdminStatus": "1.3.6.1.2.1.2.2.1.7",
    "ifOperStatus": "1.3.6.1.2.1.2.2.1.8",
    "ifInDiscards": "1.3.6.1.2.1.2.2.1.13",
    "ifInErrors": "1.3.6.1.2.1.2.2.1.14",
    "ifOutDiscards": "1.3.6.1.2.1.2.2.1.19",
    "ifOutErrors": "1.3.6.1.2.1.2.2.1.20",
    "ifHCInOctets": "1.3.6.1.2.1.31.1.1.1.6",
    "ifHCOutOctets": "1.3.6.1.2.1.31.1.1.1.10",
    "ifHighSpeed": "1.3.6.1.2.1.31.1.1.1.15",
    "ifCounterDiscontinuityTime": "1.3.6.1.2.1.31.1.1.1.19",
    "ifTableLastChange": "1.3.6.1.2.1.31.1.5",
}
APPROVED_DEVICE_VIEW_OIDS: Final = frozenset(
    {
        *(value.removesuffix(".0") for value in APPROVED_GET_OIDS),
        *APPROVED_WALK_OIDS,
    }
)


class SnmpMibContractError(ValueError):
    """Bounded generated-module or device-view closure failure."""


def _mapping(value: object, message: str) -> Mapping[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise SnmpMibContractError(message)
    return value


def _oid_set(value: object, message: str) -> frozenset[str]:
    if (
        not isinstance(value, list)
        or not all(isinstance(item, str) for item in value)
        or len(value) != len(set(value))
    ):
        raise SnmpMibContractError(message)
    return frozenset(value)


def validate_generated_module(content: bytes | str) -> None:
    """Reject generated output that escapes the exact reviewed OID closure."""
    try:
        payload = yaml.safe_load(content)
    except yaml.YAMLError:
        raise SnmpMibContractError("generated SNMP module YAML rejected") from None
    root = _mapping(payload, "generated SNMP module schema rejected")
    if set(root) != {"modules"}:
        raise SnmpMibContractError("generated SNMP module authority rejected")
    modules = _mapping(root["modules"], "generated SNMP modules rejected")
    if set(modules) != {MODULE_NAME}:
        raise SnmpMibContractError("generated SNMP module population rejected")
    module = _mapping(modules[MODULE_NAME], "generated SNMP module rejected")
    if set(module) != {"walk", "get", "metrics"}:
        raise SnmpMibContractError("generated SNMP module fields rejected")
    if _oid_set(module["walk"], "generated SNMP walk closure rejected") != (
        APPROVED_WALK_OIDS
    ):
        raise SnmpMibContractError("generated SNMP walk closure rejected")
    if _oid_set(module["get"], "generated SNMP get closure rejected") != (
        APPROVED_GET_OIDS
    ):
        raise SnmpMibContractError("generated SNMP get closure rejected")
    metrics = module["metrics"]
    if not isinstance(metrics, list):
        raise SnmpMibContractError("generated SNMP metrics rejected")
    observed_metrics: dict[str, str] = {}
    scalar_metrics = {"sysUpTime", "ifNumber", "ifTableLastChange"}
    for value in metrics:
        metric = _mapping(value, "generated SNMP metric rejected")
        name = metric.get("name")
        oid = metric.get("oid")
        if not isinstance(name, str) or not isinstance(oid, str):
            raise SnmpMibContractError("generated SNMP metric rejected")
        if name in observed_metrics:
            raise SnmpMibContractError("generated SNMP metric duplicate rejected")
        observed_metrics[name] = oid
        if name in scalar_metrics:
            if "indexes" in metric or "lookups" in metric:
                raise SnmpMibContractError("generated SNMP scalar labels rejected")
            continue
        if metric.get("indexes") != [{"labelname": "ifIndex", "type": "gauge"}]:
            raise SnmpMibContractError("generated SNMP index contract rejected")
        lookups = metric.get("lookups")
        if not isinstance(lookups, list) or len(lookups) != 1:
            raise SnmpMibContractError("generated SNMP lookup closure rejected")
        lookup_value = _mapping(lookups[0], "generated SNMP lookup rejected")
        if (
            lookup_value.get("oid") != "1.3.6.1.2.1.31.1.1.1.1"
            or lookup_value.get("labelname") != "ifName"
            or lookup_value.get("labels") != ["ifIndex"]
        ):
            raise SnmpMibContractError("generated SNMP lookup closure rejected")
    if observed_metrics != APPROVED_METRIC_OIDS:
        raise SnmpMibContractError("generated SNMP metric closure rejected")


def validate_device_view_oids(oids: frozenset[str]) -> None:
    """Require the future device view to match the generated closure exactly."""
    if oids != APPROVED_DEVICE_VIEW_OIDS:
        raise SnmpMibContractError("SNMP device view closure rejected")
