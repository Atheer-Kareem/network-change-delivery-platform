#!/usr/bin/env python3
"""Render an allowlisted, value-free subset of Terraform's JSON UI stream."""

from __future__ import annotations

import json
import re
import sys
from collections.abc import Iterable, Mapping
from typing import TextIO

_ADDRESS = re.compile(r"^(?:data\.)?cml2_[a-z0-9_]+\.[a-z0-9_]+$")
_EVENT_TYPE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_ACTIONS = frozenset({"create", "delete", "no-op", "read", "replace", "update"})
_REASONS = frozenset(
    {
        "cannot_update",
        "delete_because_no_resource_config",
        "delete_because_no_module",
        "delete_because_wrong_repetition",
        "replace_because_cannot_update",
        "replace_by_request",
        "replace_because_tainted",
    }
)
_PROGRESS_TYPES = frozenset(
    {
        "apply_complete",
        "apply_progress",
        "apply_start",
        "refresh_complete",
        "refresh_progress",
        "refresh_start",
    }
)


class UnsafeTerraformUIError(ValueError):
    """Raised when the JSON UI stream is malformed or structurally invalid."""


def _mapping(value: object) -> Mapping[str, object] | None:
    return value if isinstance(value, Mapping) else None


def _safe_address(value: object) -> str | None:
    return value if isinstance(value, str) and _ADDRESS.fullmatch(value) else None


def _safe_action(value: object) -> str | None:
    return value if isinstance(value, str) and value in _ACTIONS else None


def _safe_summary(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    single_line = " ".join(value.splitlines()).strip()
    if not single_line:
        return None
    return single_line[:500]


def _resource(event: Mapping[str, object], container: str) -> str | None:
    outer = _mapping(event.get(container))
    resource = _mapping(outer.get("resource")) if outer else None
    return _safe_address(resource.get("addr")) if resource else None


def render_event(event: Mapping[str, object]) -> str | None:
    """Return one safe display line or suppress an unapproved event."""
    event_type = event.get("type")
    if not isinstance(event_type, str) or not _EVENT_TYPE.fullmatch(event_type):
        return None

    if event_type == "version":
        terraform = event.get("terraform")
        ui = event.get("ui")
        if not isinstance(terraform, str) or not re.fullmatch(
            r"[0-9A-Za-z.+-]{1,64}", terraform
        ):
            terraform = "unknown"
        if not isinstance(ui, str) or not re.fullmatch(r"[0-9A-Za-z.+-]{1,64}", ui):
            ui = "unknown"
        return f"version terraform={terraform} ui={ui}"

    if event_type in {"planned_change", "resource_drift"}:
        change = _mapping(event.get("change"))
        resource = _mapping(change.get("resource")) if change else None
        address = _safe_address(resource.get("addr")) if resource else None
        action = _safe_action(change.get("action")) if change else None
        if not address or not action:
            return None
        kind = "planned" if event_type == "planned_change" else "drift"
        line = f"{kind} resource={address} action={action}"
        reason = change.get("reason")
        if isinstance(reason, str) and reason in _REASONS:
            line += f" reason={reason}"
        return line

    if event_type in _PROGRESS_TYPES:
        address = _resource(event, "hook")
        if not address:
            return None
        hook = _mapping(event.get("hook"))
        action = _safe_action(hook.get("action")) if hook else None
        line = f"{event_type} resource={address}"
        if action:
            line += f" action={action}"
        elapsed = event.get("elapsed_seconds")
        if (
            isinstance(elapsed, (int, float))
            and not isinstance(elapsed, bool)
            and 0 <= elapsed <= 86_400
        ):
            line += f" elapsed={elapsed:g}s"
        return line

    if event_type == "change_summary":
        changes = _mapping(event.get("changes"))
        if not changes:
            return None
        counts = []
        for key, label in (("add", "add"), ("change", "change"), ("remove", "destroy")):
            value = changes.get(key)
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                return None
            counts.append(f"{label}={value}")
        operation = changes.get("operation")
        prefix = operation if operation in {"plan", "apply"} else "summary"
        return f"{prefix} {' '.join(counts)}"

    if event_type == "diagnostic":
        diagnostic = _mapping(event.get("diagnostic"))
        if not diagnostic:
            return None
        severity = diagnostic.get("severity")
        summary = _safe_summary(diagnostic.get("summary"))
        if severity not in {"error", "warning"} or not summary:
            return None
        return f"diagnostic severity={severity} summary={summary}"

    return None


def render_stream(lines: Iterable[str], output: TextIO) -> None:
    """Parse and render a JSON-lines stream without echoing rejected input."""
    for line in lines:
        try:
            event = json.loads(line)
        except (json.JSONDecodeError, TypeError) as error:
            raise UnsafeTerraformUIError(
                "malformed Terraform JSON UI stream"
            ) from error
        if not isinstance(event, Mapping):
            raise UnsafeTerraformUIError("invalid Terraform JSON UI event")
        rendered = render_event(event)
        if rendered is not None:
            print(rendered, file=output, flush=True)


def main() -> int:
    try:
        render_stream(sys.stdin, sys.stdout)
    except UnsafeTerraformUIError:
        print("terraform safe UI rejected malformed input", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
