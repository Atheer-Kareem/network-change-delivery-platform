"""Deterministic Prometheus SNMP scrape and identity normalization rendering."""

from __future__ import annotations

import re

import yaml

from network_change_delivery.snmp_mib import APPROVED_METRIC_OIDS, MODULE_NAME
from network_change_delivery.snmp_telemetry import SnmpInterfaceMapping

SNMP_JOB_NAME = "ncdp-snmp-interface"
SCALAR_METRICS = frozenset({"sysUpTime", "ifNumber", "ifTableLastChange"})
TABLE_METRICS = frozenset(APPROVED_METRIC_OIDS) - SCALAR_METRICS


class SnmpPrometheusConfigError(ValueError):
    """Raised when rendered scrape identity would be ambiguous or unbounded."""


def _prometheus_regex(value: str) -> str:
    return re.escape(value)


def _metric_regex(values: frozenset[str]) -> str:
    return "(?:" + "|".join(re.escape(value) for value in sorted(values)) + ")"


def render_snmp_prometheus_config(
    base_content: bytes,
    mappings: tuple[SnmpInterfaceMapping, ...],
) -> bytes:
    """Append an SNMP job without changing committed production YAML."""
    try:
        config = yaml.safe_load(base_content)
    except yaml.YAMLError:
        raise SnmpPrometheusConfigError(
            "Prometheus base configuration rejected"
        ) from None
    if not isinstance(config, dict) or not isinstance(
        config.get("scrape_configs"), list
    ):
        raise SnmpPrometheusConfigError("Prometheus base configuration rejected")
    jobs = config["scrape_configs"]
    if any(
        isinstance(job, dict) and job.get("job_name") == SNMP_JOB_NAME for job in jobs
    ):
        raise SnmpPrometheusConfigError("Prometheus SNMP job already exists")
    devices = [mapping.device for mapping in mappings]
    if not mappings or len(devices) != len(set(devices)):
        raise SnmpPrometheusConfigError("SNMP interface mappings rejected")
    interfaces = [item for mapping in mappings for item in mapping.interfaces]
    identities = [item.inventory_object_id for item in interfaces]
    if len(identities) != len(set(identities)):
        raise SnmpPrometheusConfigError("SNMP interface mappings rejected")
    metric_relabels: list[dict[str, object]] = []
    interface_pairs = [
        (mapping, interface) for mapping in mappings for interface in mapping.interfaces
    ]
    for device_mapping, interface in sorted(
        interface_pairs,
        key=lambda item: int(item[1].inventory_object_id.rsplit(":", 1)[1]),
    ):
        match = (
            f"{_prometheus_regex(device_mapping.device)};"
            f"{_prometheus_regex(interface.interface_name)}"
        )
        metric_relabels.extend(
            [
                {
                    "source_labels": ["instance", "ifName"],
                    "regex": match,
                    "target_label": "interface_id",
                    "replacement": interface.inventory_object_id,
                },
                {
                    "source_labels": ["instance", "ifName"],
                    "regex": match,
                    "target_label": "interface_name",
                    "replacement": interface.interface_name,
                },
            ]
        )
    metric_relabels.extend(
        [
            {
                "source_labels": ["__name__", "interface_id"],
                "regex": f"{_metric_regex(TABLE_METRICS)};",
                "action": "drop",
            },
            {"regex": "^(?:ifName|ifIndex)$", "action": "labeldrop"},
        ]
    )
    jobs.append(
        {
            "job_name": SNMP_JOB_NAME,
            "metrics_path": "/snmp",
            "scrape_interval": "5s",
            "scrape_timeout": "4s",
            "params": {"module": [MODULE_NAME]},
            "file_sd_configs": [
                {
                    "files": ["/etc/ncdp/targets/snmp-targets.json"],
                    "refresh_interval": "5s",
                }
            ],
            "relabel_configs": [
                {
                    "source_labels": ["__address__"],
                    "target_label": "__param_target",
                },
                {"target_label": "__address__", "replacement": "snmp_exporter:9116"},
            ],
            "metric_relabel_configs": metric_relabels,
        }
    )
    return yaml.safe_dump(config, sort_keys=False, width=100).encode()
