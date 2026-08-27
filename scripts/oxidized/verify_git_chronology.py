#!/usr/bin/env python3
"""Verify metadata-only path chronology against synthetic writer results."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from network_change_delivery.oxidized_history import OxidizedHistoryRepository


def main() -> int:
    if len(sys.argv) != 3:
        print("synthetic chronology verification arguments rejected", file=sys.stderr)
        return 2
    repository = Path(sys.argv[1])
    results_path = Path(sys.argv[2])
    try:
        evidence = json.loads(results_path.read_text())
        steps = evidence["results"]
        node1 = OxidizedHistoryRepository(repository).latest_revision("netbox-device-1")
        node2 = OxidizedHistoryRepository(repository).latest_revision("netbox-device-2")
        assert evidence["bare"] is True
        assert evidence["remotes"] == []
        assert evidence["index_present"] is True
        assert evidence["hook_entries"] in ([], ["README.sample"])
        assert evidence["executable_hooks"] == []
        assert evidence["object_format"] == "sha1"
        assert [step["commit_created"] for step in steps] == [
            True,
            False,
            True,
            True,
            False,
            True,
        ]
        assert [step["head_changed"] for step in steps] == [
            True,
            False,
            True,
            True,
            False,
            True,
        ]
        assert steps[0]["head"] == steps[1]["head"]
        assert steps[0]["blob"] == steps[1]["blob"]
        assert steps[2]["blob"] == steps[4]["blob"]
        assert steps[3]["head"] == steps[4]["head"]
        assert steps[5]["blob"] != steps[4]["blob"]
        assert [step["commit_count"] for step in steps] == [1, 1, 2, 3, 3, 4]
        assert [step["path_revision_count"] for step in steps] == [1, 1, 2, 1, 2, 3]
        assert all(
            step["author_name"] == "NCDP Oxidized"
            and step["author_email"] == "oxidized@ncdp.local"
            for step in steps
            if step["commit_created"]
        )
        assert node1.commit == steps[5]["head"]
        assert node1.blob == steps[5]["blob"]
        assert node2.commit == steps[3]["head"]
        assert node2.blob == steps[3]["blob"]
        versions = evidence["public_versions"]
        assert versions["node1_count"] == 3
        assert versions["node1_latest"] == steps[5]["head"]
        assert versions["node2_count"] == 1
        assert versions["node2_latest"] == steps[3]["head"]
        assert versions["metadata_keys"] == ["author", "date", "message", "oid", "time"]
        assert node1.config_path == "managed/netbox-device-1"
        assert node2.config_path == "managed/netbox-device-2"
    except (AssertionError, KeyError, OSError, TypeError, ValueError):
        print("synthetic Oxidized chronology verification failed", file=sys.stderr)
        return 2
    print("Oxidized Git chronology: PASS (6 stores, 4 commits, path-scoped metadata)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
