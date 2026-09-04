#!/usr/bin/env python3
"""Guarded destroy-only recovery for one retained profiled staging run.

The command never creates or starts a lab. ``--execute`` is a separately
reviewed authority gate; without it, the command validates the retained run and
the exact destroy graph only.
"""

from __future__ import annotations

import argparse
import json
import os
import ssl
import subprocess
from pathlib import Path

import httpx

from network_change_delivery.profiled_staging import (
    ProfiledStagingError,
    validate_destroy_only_plan,
    validate_private_run_directory,
)

ROOT = Path(__file__).resolve().parents[1]
TERRAFORM_ROOT = ROOT / "infrastructure" / "cml" / "profiled-staging"


def _terraform(run: Path, arguments: list[str], *, phase: str) -> str:
    result = subprocess.run(
        ["terraform", f"-chdir={TERRAFORM_ROOT}", *arguments],
        cwd=ROOT,
        env={**os.environ, "TF_DATA_DIR": str(run / "terraform-data")},
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise ProfiledStagingError(f"profiled staging recovery {phase} rejected")
    return result.stdout


def _state_addresses(run: Path) -> set[str]:
    return {
        line
        for line in _terraform(
            run, ["state", "list"], phase="state inspection"
        ).splitlines()
        if line
    }


def _destroy_actions(run: Path, plan: Path) -> dict[str, str]:
    _terraform(
        run, ["plan", "-destroy", "-out", str(plan), "-input=false"], phase="plan"
    )
    try:
        payload = json.loads(
            _terraform(run, ["show", "-json", str(plan)], phase="plan inspection")
        )
        changes = payload["resource_changes"]
    except (KeyError, TypeError, ValueError):
        raise ProfiledStagingError("profiled staging recovery plan rejected") from None
    if not isinstance(changes, list):
        raise ProfiledStagingError("profiled staging recovery plan rejected")
    actions: dict[str, str] = {}
    for change in changes:
        if not isinstance(change, dict):
            raise ProfiledStagingError("profiled staging recovery plan rejected")
        address = change.get("address")
        data = change.get("change")
        verbs = data.get("actions") if isinstance(data, dict) else None
        if not isinstance(address, str) or verbs != ["delete"]:
            raise ProfiledStagingError("profiled staging recovery plan rejected")
        actions[address] = "delete"
    return actions


def _lab_binding(run: Path) -> tuple[str, str]:
    try:
        output = json.loads(_terraform(run, ["output", "-json"], phase="output"))
        title = output["lab_title"]["value"]
        lab_id = output["lab_id"]["value"]
    except (KeyError, TypeError, ValueError):
        raise ProfiledStagingError(
            "profiled staging recovery lab binding rejected"
        ) from None
    if not isinstance(title, str) or not isinstance(lab_id, str):
        raise ProfiledStagingError("profiled staging recovery lab binding rejected")
    return lab_id, title


def _verify_absence(lab_id: str) -> None:
    address = os.environ.get("CML2_ADDRESS")
    token = os.environ.get("CML2_TOKEN")
    certificate = os.environ.get("CML2_CACERT")
    if not address or not token or not certificate:
        raise ProfiledStagingError(
            "profiled staging recovery absence authority missing"
        )
    client = httpx.Client(
        base_url=address.rstrip("/"),
        headers={"Authorization": f"Bearer {token}"},
        verify=ssl.create_default_context(cadata=certificate),
        timeout=10,
        trust_env=False,
    )
    try:
        response = client.get(f"/api/v0/labs/{lab_id}")
    except httpx.HTTPError:
        raise ProfiledStagingError(
            "profiled staging recovery absence not proven"
        ) from None
    finally:
        client.close()
    if response.status_code != 404:
        raise ProfiledStagingError("profiled staging recovery absence not proven")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--run-directory", type=Path, required=True)
    parser.add_argument("--execute", action="store_true")
    arguments = parser.parse_args()
    try:
        run = validate_private_run_directory(arguments.run_directory, ROOT)
        if run.name != arguments.run_id or not (run / "terraform.tfstate").is_file():
            raise ProfiledStagingError("retained run identity rejected")
        lab_id, lab_title = _lab_binding(run)
        if lab_title != f"NCDP Staging {arguments.run_id}":
            raise ProfiledStagingError("retained staging lab identity rejected")
        plan = run / "destroy.tfplan"
        state = _state_addresses(run)
        validate_destroy_only_plan(state, _destroy_actions(run, plan))
        if not arguments.execute:
            print("profiled staging destroy-only recovery is admitted but not executed")
            return 2
        _terraform(run, ["apply", "-input=false", str(plan)], phase="destroy")
        if _state_addresses(run):
            raise ProfiledStagingError("profiled staging recovery absence not proven")
        _verify_absence(lab_id)
        for path in (run / "terraform.tfstate", plan):
            if path.exists() and not path.is_symlink():
                path.unlink()
    except (OSError, ValueError, ProfiledStagingError) as error:
        print(f"profiled staging recovery rejected: {error}")
        return 2
    print("profiled staging destroy-only recovery completed")
    return 0


if __name__ == "__main__":  # pragma: no cover - explicit operator entry point
    raise SystemExit(main())
