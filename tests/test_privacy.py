from __future__ import annotations

import asyncio
import json
import sys

from fastmcp import Client, FastMCP

from deepagents_mcp_privacy import (
    PrivacyPolicy,
    create_private_mcp_client,
    create_private_proxy,
    sanitize_value,
)


def _render(value: object) -> str:
    return json.dumps(value, sort_keys=True)


def test_schema_only_table_contains_no_observed_values() -> None:
    payload = {
        "rows": [
            {"customer_id": "C-001", "full_name": "Alice Smith", "segment": "Enterprise", "spend": 125.5},
            {"customer_id": "C-002", "full_name": "Bob Jones", "segment": "Consumer", "spend": 87.0},
        ]
    }

    safe = sanitize_value(payload)
    rendered = _render(safe)

    assert safe["source_kind"] == "table"
    assert safe["result"] == {"withheld": True, "reason": "Schema-only policy is active"}
    assert set(safe["schema"]["columns"]) == {"customer_id", "full_name", "segment", "spend"}
    assert safe["example_row"]["customer_id"] == "SYNTHETIC"
    for secret in ("C-001", "Alice Smith", "Enterprise", "125.5", '"count"'):
        assert secret not in rendered


def test_analytics_are_explicit_and_small_groups_are_suppressed() -> None:
    rows = [{"region": "North", "amount": index + 1} for index in range(6)]
    policy = PrivacyPolicy(expose_counts=True, expose_aggregates=True)

    safe = sanitize_value({"rows": rows}, policy=policy)

    assert safe["result"]["count"] == 6
    assert safe["result"]["numeric_aggregates"]["amount"] == {
        "average": 3.5,
        "maximum": 6.0,
        "minimum": 1.0,
        "sum": 21.0,
    }
    assert safe["result"]["category_counts"]["region"] == {"SYNTHETIC_GROUP_1": 6}

    suppressed = sanitize_value({"rows": rows[:4]}, policy=policy)
    assert suppressed["result"]["numeric_aggregates"]["suppressed"] is True
    assert "category_counts" not in suppressed["result"]


def test_nested_structure_discloses_shapes_not_values() -> None:
    payload = {
        "service": "payments-api",
        "healthy": True,
        "latency_ms": 19.3,
        "nodes": [
            {"hostname": "prod-node-01", "ip_address": "10.2.3.4"},
            {"hostname": "prod-node-02", "ip_address": "10.2.3.5"},
        ],
    }

    safe = sanitize_value(payload)
    rendered = _render(safe)

    assert safe["source_kind"] == "structured"
    assert safe["shape"]["nodes"]["type"] == "array"
    assert "length" not in safe["shape"]["nodes"]
    for secret in ("payments-api", "19.3", "prod-node-01", "10.2.3.4"):
        assert secret not in rendered


def test_data_encoded_as_mapping_keys_is_replaced() -> None:
    payload = {
        "counts_by_user": {
            "alice@example.com": 5,
            "10.2.3.4": 7,
            "Private Person": 9,
        }
    }

    safe = sanitize_value(payload)
    rendered = _render(safe)

    assert set(safe["shape"]["counts_by_user"]) == {
        "SYNTHETIC_FIELD_1",
        "SYNTHETIC_FIELD_2",
        "SYNTHETIC_FIELD_3",
    }
    for secret in ("alice@example.com", "10.2.3.4", "Private Person"):
        assert secret not in rendered


def test_json_text_is_sanitized_and_plain_text_is_withheld() -> None:
    json_safe = sanitize_value('{"token":"secret-token","usage":42}')
    plain_safe = sanitize_value("Customer Alice owes 42 dollars")

    assert json_safe["source_kind"] == "structured"
    assert "secret-token" not in _render(json_safe)
    assert "42" not in _render(json_safe)
    assert plain_safe["source_kind"] == "text"
    assert plain_safe["withheld"] is True
    assert plain_safe["reason"] == "Unstructured text is withheld by default"


def test_custom_text_sanitizer_still_removes_returned_values() -> None:
    policy = PrivacyPolicy(
        text_sanitizers={
            "status": lambda text: {"summary": text.split(":", 1)[0], "severity": 9}
        }
    )

    safe = sanitize_value("Database degraded: private host db-01", policy=policy, tool_name="status")
    rendered = _render(safe)

    assert safe["source_kind"] == "structured"
    assert "Database degraded" not in rendered
    assert "db-01" not in rendered
    assert '"example": 0' in rendered


def test_empty_and_scalar_values_fail_closed() -> None:
    assert sanitize_value([])["shape"] == {"items": None, "type": "array"}
    assert sanitize_value(None)["shape"]["example"] is None
    assert sanitize_value(123)["shape"]["example"] == 0


def test_proxy_preserves_tool_schema_and_replaces_results() -> None:
    async def scenario() -> None:
        upstream = FastMCP("source")

        @upstream.tool
        def lookup(account_id: str, limit: int = 10) -> dict[str, object]:
            """Look up private account records."""
            return {
                "rows": [
                    {"account_id": account_id, "owner_name": "Private Person", "balance": 9000.0}
                ]
            }

        proxy = create_private_proxy(upstream)
        async with Client(proxy) as client:
            tools = await client.list_tools()
            result = await client.call_tool("lookup", {"account_id": "SECRET-7"})

        tool = next(item for item in tools if item.name == "lookup")
        assert tool.description == "Look up private account records."
        assert set(tool.inputSchema["properties"]) == {"account_id", "limit"}
        rendered = str(result)
        for secret in ("SECRET-7", "Private Person", "9000"):
            assert secret not in rendered

    asyncio.run(scenario())


def test_proxy_replaces_upstream_error_details() -> None:
    async def scenario() -> None:
        upstream = FastMCP("source")

        @upstream.tool
        def fail(secret: str) -> str:
            raise RuntimeError(f"sensitive failure: {secret}")

        proxy = create_private_proxy(upstream)
        async with Client(proxy) as client:
            result = await client.call_tool("fail", {"secret": "DO-NOT-LEAK"}, raise_on_error=False)

        rendered = str(result)
        assert result.is_error
        assert "DO-NOT-LEAK" not in rendered
        assert "sensitive failure" not in rendered
        assert "details withheld by privacy policy" in rendered

    asyncio.run(scenario())


def test_private_client_spawns_gateway_before_agent_process() -> None:
    async def scenario() -> None:
        connections = {
            "private": {
                "transport": "stdio",
                "command": sys.executable,
                "args": ["-m", "deepagents_mcp_demo.server"],
            }
        }
        tools = await create_private_mcp_client(connections).get_tools()
        result = await next(tool for tool in tools if tool.name == "get_products").ainvoke({})
        payload = json.loads(result[0]["text"])
        rendered = _render(payload)

        assert len(tools) == 34
        assert payload["source_kind"] == "structured"
        assert payload["privacy"]["raw_data_shared"] is False
        assert payload["shape"]["result"]["count"]["example"] == 0
        assert "Products" not in rendered
        assert "2346.87" not in rendered
        assert '"rows"' not in rendered

    asyncio.run(scenario())