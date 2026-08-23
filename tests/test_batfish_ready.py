import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts/buildkite"))
import batfish_ready  # noqa: E402


def test_readiness_uses_configured_batfish_host(monkeypatch) -> None:
    observed = {}

    class Session:
        def __init__(self, *, host, port):
            observed.update(host=host, port=port)

        @staticmethod
        def _get_bf_version():
            return "test-version"

    monkeypatch.setenv("NCDP_BATFISH_HOST", "batfish")
    monkeypatch.setattr(batfish_ready, "Session", Session)
    assert batfish_ready.check_batfish() == "test-version"
    assert observed == {"host": "batfish", "port": 9996}


def test_readiness_fails_closed_without_version(monkeypatch) -> None:
    class Session:
        def __init__(self, *, host, port):
            pass

        @staticmethod
        def _get_bf_version():
            return ""

    monkeypatch.setattr(batfish_ready, "Session", Session)
    with pytest.raises(RuntimeError, match="server version unavailable"):
        batfish_ready.check_batfish()
