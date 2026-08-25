import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "scripts/terraform_cml_safe_ui.py"
SENTINELS = {
    "message": "SENTINEL_MESSAGE_SECRET",
    "detail": "SENTINEL_DIAGNOSTIC_DETAIL",
    "output": "SENTINEL_OUTPUT_VALUE",
    "nested": "SENTINEL_UNKNOWN_NESTED",
    "resource": "SENTINEL_RESOURCE_DATA",
}


def run_ui(events: list[object] | str) -> subprocess.CompletedProcess[str]:
    if isinstance(events, str):
        payload = events
    else:
        payload = "".join(json.dumps(event) + "\n" for event in events)
    return subprocess.run(
        [sys.executable, str(SCRIPT)],
        input=payload,
        text=True,
        capture_output=True,
        check=False,
    )


def test_allowlisted_events_emit_only_structural_metadata() -> None:
    events = [
        {
            "type": "version",
            "terraform": "1.15.8",
            "ui": "1.2",
            "@message": SENTINELS["message"],
        },
        {
            "type": "planned_change",
            "change": {
                "resource": {
                    "addr": "cml2_node.edge_junos_01",
                    "data": SENTINELS["resource"],
                },
                "action": "replace",
                "reason": "cannot_update",
                "after": {"configuration": SENTINELS["nested"]},
            },
        },
        {
            "type": "resource_drift",
            "change": {
                "resource": {"addr": "cml2_lab.twin"},
                "action": "update",
            },
        },
        {
            "type": "apply_progress",
            "hook": {
                "resource": {"addr": "cml2_node.edge_junos_01"},
                "action": "replace",
                "arbitrary": SENTINELS["resource"],
            },
            "elapsed_seconds": 12,
            "@message": SENTINELS["message"],
        },
        {
            "type": "change_summary",
            "changes": {"add": 4, "change": 1, "remove": 4, "operation": "plan"},
            "outputs": {"value": SENTINELS["output"]},
        },
        {
            "type": "diagnostic",
            "diagnostic": {
                "severity": "warning",
                "summary": "bounded summary",
                "detail": SENTINELS["detail"],
            },
        },
        {
            "type": "outputs",
            "outputs": {"unsafe": {"value": SENTINELS["output"]}},
        },
        {
            "type": "future_event",
            "unknown": {"secret": SENTINELS["nested"]},
            "@message": SENTINELS["message"],
        },
    ]

    result = run_ui(events)

    assert result.returncode == 0
    assert result.stderr == ""
    assert result.stdout.splitlines() == [
        "version terraform=1.15.8 ui=1.2",
        "planned resource=cml2_node.edge_junos_01 action=replace reason=cannot_update",
        "drift resource=cml2_lab.twin action=update",
        "apply_progress resource=cml2_node.edge_junos_01 action=replace elapsed=12s",
        "plan add=4 change=1 destroy=4",
        "diagnostic severity=warning summary=bounded summary",
    ]
    for sentinel in SENTINELS.values():
        assert sentinel not in result.stdout


def test_malformed_json_fails_closed_without_echoing_input() -> None:
    secret = "MALFORMED_SENTINEL_SECRET"
    result = run_ui('{"type":"version","unsafe":"' + secret)
    assert result.returncode == 2
    assert result.stdout == ""
    assert result.stderr == "terraform safe UI rejected malformed input\n"
    assert secret not in result.stderr


def test_invalid_structural_fields_are_suppressed() -> None:
    secret = "ADDRESS_SENTINEL_SECRET"
    result = run_ui(
        [
            {
                "type": "planned_change",
                "change": {
                    "resource": {"addr": f"cml2_node.edge[{secret}]"},
                    "action": "replace",
                },
            },
            {
                "type": "change_summary",
                "changes": {"add": 1, "change": secret, "remove": 1},
            },
        ]
    )
    assert result.returncode == 0
    assert result.stdout == ""
    assert result.stderr == ""
