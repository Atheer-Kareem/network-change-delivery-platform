from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

from network_change_delivery.snmp_prometheus import (
    SCALAR_METRICS,
    SNMP_JOB_NAME,
    TABLE_METRICS,
    SnmpPrometheusConfigError,
    render_snmp_prometheus_config,
)
from network_change_delivery.snmp_telemetry import (
    ExpectedSnmpInterface,
    ExpectedSnmpInterfacePopulation,
    ObservedSnmpInterface,
    normalize_interfaces,
)

ROOT = Path(__file__).parents[1]
BASE = (ROOT / "infrastructure/observability/prometheus.yml").read_bytes()


def mapping(device_number: int, offset: int = 0):
    device = f"netbox:dcim.device:{device_number}"
    return normalize_interfaces(
        ExpectedSnmpInterfacePopulation(
            device=device,
            pagination_complete=True,
            interfaces=(
                ExpectedSnmpInterface(
                    device=device,
                    inventory_object_id=f"netbox:dcim.interface:{offset + 1}",
                    name="eth0",
                ),
                ExpectedSnmpInterface(
                    device=device,
                    inventory_object_id=f"netbox:dcim.interface:{offset + 2}",
                    name="lo",
                ),
            ),
        ),
        (
            ObservedSnmpInterface(if_index=2, if_name="eth0"),
            ObservedSnmpInterface(if_index=1, if_name="lo"),
            ObservedSnmpInterface(if_index=99, if_name="pseudo0"),
        ),
    )


def snmp_job(content: bytes) -> dict[str, object]:
    jobs = yaml.safe_load(content)["scrape_configs"]
    return next(item for item in jobs if item["job_name"] == SNMP_JOB_NAME)


def test_renderer_adds_private_scrape_flow_and_exact_stable_mappings() -> None:
    rendered = render_snmp_prometheus_config(BASE, (mapping(1), mapping(2, 2)))
    job = snmp_job(rendered)
    assert job["metrics_path"] == "/snmp"
    assert job["params"] == {"module": ["ncdp_if_mib"]}
    assert job["file_sd_configs"][0]["files"] == ["/etc/ncdp/targets/snmp-targets.json"]
    assert job["relabel_configs"][-1] == {
        "target_label": "__address__",
        "replacement": "snmp_exporter:9116",
    }
    replacements = {
        item.get("replacement")
        for item in job["metric_relabel_configs"]
        if item.get("target_label") == "interface_id"
    }
    assert replacements == {
        "netbox:dcim.interface:1",
        "netbox:dcim.interface:2",
        "netbox:dcim.interface:3",
        "netbox:dcim.interface:4",
    }
    mapping_rules = [
        item
        for item in job["metric_relabel_configs"]
        if item.get("target_label") == "interface_id"
    ]
    assert all(
        item["source_labels"] == ["instance", "ifName"] for item in mapping_rules
    )
    assert {(item["regex"], item["replacement"]) for item in mapping_rules} == {
        (r"netbox:dcim\.device:1;eth0", "netbox:dcim.interface:1"),
        (r"netbox:dcim\.device:1;lo", "netbox:dcim.interface:2"),
        (r"netbox:dcim\.device:2;eth0", "netbox:dcim.interface:3"),
        (r"netbox:dcim\.device:2;lo", "netbox:dcim.interface:4"),
    }
    rendered_text = rendered.decode()
    for forbidden in ("__param_auth.*target_label", "ifAlias", "ifDescr", "password"):
        assert forbidden not in rendered_text


def test_table_drop_does_not_drop_device_scalar_metrics() -> None:
    job = snmp_job(render_snmp_prometheus_config(BASE, (mapping(1),)))
    drop = next(
        item for item in job["metric_relabel_configs"] if item.get("action") == "drop"
    )
    expression = re.compile(drop["regex"])
    assert all(expression.fullmatch(f"{name};") for name in TABLE_METRICS)
    assert all(expression.fullmatch(f"{name};") is None for name in SCALAR_METRICS)
    assert job["metric_relabel_configs"][-1] == {
        "regex": "^(?:ifName|ifIndex)$",
        "action": "labeldrop",
    }


def test_renderer_rejects_duplicate_device_or_existing_job() -> None:
    one = mapping(1)
    with pytest.raises(SnmpPrometheusConfigError, match="mappings rejected"):
        render_snmp_prometheus_config(BASE, (one, one))
    existing = yaml.safe_load(BASE)
    existing["scrape_configs"].append({"job_name": SNMP_JOB_NAME})
    with pytest.raises(SnmpPrometheusConfigError, match="already exists"):
        render_snmp_prometheus_config(yaml.safe_dump(existing).encode(), (one,))
