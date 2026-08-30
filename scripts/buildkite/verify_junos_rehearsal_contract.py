#!/usr/bin/env python3
"""Temporary: fail closed unless this is the bounded JUNOS-001 rehearsal."""

from __future__ import annotations

import os
from pathlib import Path

import yaml

from network_change_delivery.buildkite_deployment import (
    load_live_deployment_request,
)
from network_change_delivery.snmp_provisioning import SnmpProvisioningPlan

ROOT = Path(__file__).resolve().parents[2]


def main() -> int:
    pull_request = os.environ.get("BUILDKITE_PULL_REQUEST", "")
    if not pull_request or pull_request == "false":
        raise ValueError("Junos rehearsal requires a pull request build")
    plan = SnmpProvisioningPlan.model_validate_json(
        (ROOT / "deployments/live/promotion/plan.json").read_text(encoding="utf-8")
    )
    request = load_live_deployment_request(ROOT / "deployments/live/request.yaml")
    request.verify_plan(plan)
    if (
        plan.change_id != "CHG-SNMP-11C3-JUNOS-001"
        or plan.inventory_object_id != "netbox:dcim.device:2"
        or plan.host != "192.168.4.20"
        or plan.port != 830
        or plan.platform != "junos"
        or plan.transaction_strategy != "junos_commit_confirmed"
        or plan.confirmed_timeout_minutes != 5
        or not plan.preconditions.safe_to_create_for("junos")
    ):
        raise ValueError("Junos rehearsal source contract rejected")
    pipeline = yaml.safe_load(
        (ROOT / ".buildkite/pipeline.yml").read_text(encoding="utf-8")
    )
    steps = pipeline.get("steps") if isinstance(pipeline, dict) else None
    if not isinstance(steps, list) or len(steps) != 4:
        raise ValueError("Junos rehearsal pipeline contract rejected")
    keys = [step.get("key") for step in steps if isinstance(step, dict)]
    if keys != [
        "rehearsal-contract",
        "rehearsal-promotion",
        "junos-rehearsal-approval",
        "cml-staging",
    ]:
        raise ValueError("Junos rehearsal pipeline order rejected")
    serialized = (ROOT / ".buildkite/pipeline.yml").read_text(encoding="utf-8")
    if "ncdp-deploy" in serialized or "deploy-gate" in serialized:
        raise ValueError("production deployment authority leaked into rehearsal")
    if "urn:ncdp:openbao:deploy" in serialized:
        raise ValueError("live OpenBao audience leaked into rehearsal")
    print("JUNOS-001 exact PR rehearsal contract: VERIFIED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
