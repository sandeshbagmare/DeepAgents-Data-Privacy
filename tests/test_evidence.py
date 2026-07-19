from __future__ import annotations

import importlib.util
from pathlib import Path

from deepagents_mcp_privacy import sanitize_value

ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "scripts" / "capture-privacy-evidence.py"


def load_capture_module():
    spec = importlib.util.spec_from_file_location("capture_privacy_evidence", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_all_fixture_canaries_are_absent_after_sanitization() -> None:
    capture = load_capture_module()

    for payload in capture.RAW_EXAMPLES.values():
        sanitized = sanitize_value(payload)
        assert capture.contains_secret(sanitized) == []


def test_external_connection_classification() -> None:
    capture = load_capture_module()

    assert not capture.is_external_connection(
        {"RemoteAddress": "127.0.0.1", "RemotePort": 50123}
    )
    assert not capture.is_external_connection(
        {"RemoteAddress": "0.0.0.0", "RemotePort": 0}
    )
    assert capture.is_external_connection(
        {"RemoteAddress": "203.0.113.10", "RemotePort": 443}
    )