from __future__ import annotations

import asyncio
import json
import sys
from collections import namedtuple
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal
from enum import Enum
from pathlib import Path
from uuid import UUID

from fastmcp import Client, FastMCP
from pydantic import BaseModel

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


@dataclass
class PrivateRecord:
    customer_id: str
    amount: Decimal


class PrivateStatus(BaseModel):
    hostname: str
    observed_at: datetime


class PrivateLevel(Enum):
    CRITICAL = "private-critical"


def test_common_python_structured_types_preserve_shape_only() -> None:
    Coordinate = namedtuple("Coordinate", ["latitude", "longitude"])
    cases = {
        "tuple_table": (
            ({"customer_name": "Alice", "amount": 12}, {"customer_name": "Bob", "amount": 20}),
            ("Alice", "Bob", "12", "20"),
        ),
        "named_tuple": (Coordinate(51.5, -0.1), ("51.5", "-0.1")),
        "dataclass": (PrivateRecord("C-001", Decimal("42.50")), ("C-001", "42.50")),
        "pydantic": (
            PrivateStatus(hostname="prod-01", observed_at=datetime(2026, 7, 19, 10, 30)),
            ("prod-01", "2026", "10:30"),
        ),
        "set": ({"private-alpha", "private-beta"}, ("private-alpha", "private-beta")),
        "frozen_set": (frozenset({"private-gamma"}), ("private-gamma",)),
        "binary": (b"private-bytes", ("private-bytes",)),
        "date": (date(2026, 7, 19), ("2026", "7", "19")),
        "time": (time(10, 30), ("10:30",)),
        "decimal": (Decimal("99.9"), ("99.9",)),
        "uuid": (UUID("12345678-1234-5678-1234-567812345678"), ("12345678",)),
        "path": (Path("C:/private/customer.csv"), ("private", "customer.csv")),
        "enum": (PrivateLevel.CRITICAL, ("private-critical",)),
    }

    for value, secrets in cases.values():
        safe = sanitize_value(value)
        rendered = _render(safe)
        assert safe["privacy"]["raw_data_shared"] is False
        for secret in secrets:
            assert secret not in rendered

    assert sanitize_value(cases["tuple_table"][0])["source_kind"] == "table"
    assert set(sanitize_value(cases["dataclass"][0])["shape"]) == {"customer_id", "amount"}
    assert set(sanitize_value(cases["pydantic"][0])["shape"]) == {"hostname", "observed_at"}
    assert sanitize_value(cases["set"][0])["shape"]["type"] == "array"


def test_non_string_keys_cycles_and_depth_are_safely_bounded() -> None:
    keyed = sanitize_value({7: "private-value", ("account", 1): 99})
    assert set(keyed["shape"]) == {"SYNTHETIC_FIELD_1", "SYNTHETIC_FIELD_2"}
    assert "private-value" not in _render(keyed)

    cycle: dict[str, object] = {"label": "private-cycle"}
    cycle["self"] = cycle
    safe_cycle = sanitize_value(cycle)
    assert safe_cycle["shape"]["self"] == {"type": "recursive_reference", "withheld": True}
    assert "private-cycle" not in _render(safe_cycle)

    deep: dict[str, object] = {"secret": "private-deep"}
    for _ in range(40):
        deep = {"nested": deep}
    safe_deep = sanitize_value(deep)
    assert "maximum_depth" in _render(safe_deep)
    assert "private-deep" not in _render(safe_deep)


def test_hostile_custom_mapping_fails_closed() -> None:
    class HostileMapping(Mapping[str, object]):
        def __iter__(self):
            raise RuntimeError("private iterator failure")

        def __len__(self) -> int:
            return 1

        def __getitem__(self, key: str) -> object:
            raise RuntimeError(f"private value for {key}")

    safe = sanitize_value(HostileMapping())

    assert safe["source_kind"] == "unsupported"
    assert safe["withheld"] is True
    assert "private" not in _render(safe)


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


def test_proxy_passthrough_is_limited_to_explicit_tools() -> None:
    async def scenario() -> None:
        upstream = FastMCP("source")

        @upstream.tool
        def approved() -> dict[str, object]:
            return {"rows": [{"account_id": "RAW-APPROVED", "balance": 9000.0}]}

        @upstream.tool
        def private() -> dict[str, object]:
            return {"rows": [{"account_id": "RAW-PRIVATE", "balance": 8000.0}]}

        proxy = create_private_proxy(
            upstream,
            policy=PrivacyPolicy(passthrough_tools=("approved",)),
        )
        async with Client(proxy) as client:
            approved_result = await client.call_tool("approved", {})
            private_result = await client.call_tool("private", {})

        assert "RAW-APPROVED" in str(approved_result)
        assert "9000" in str(approved_result)
        assert "RAW-PRIVATE" not in str(private_result)
        assert "8000" not in str(private_result)

    asyncio.run(scenario())


def test_proxy_wildcard_passthrough_keeps_errors_private() -> None:
    async def scenario() -> None:
        upstream = FastMCP("source")

        @upstream.tool
        def raw() -> dict[str, str]:
            return {"secret": "RAW-FOR-ALL"}

        @upstream.tool
        def fail() -> str:
            raise RuntimeError("RAW-ERROR")

        proxy = create_private_proxy(
            upstream,
            policy=PrivacyPolicy(passthrough_tools=("*",)),
        )
        async with Client(proxy) as client:
            raw_result = await client.call_tool("raw", {})
            error_result = await client.call_tool("fail", {}, raise_on_error=False)

        assert "RAW-FOR-ALL" in str(raw_result)
        assert "RAW-ERROR" not in str(error_result)
        assert "details withheld by privacy policy" in str(error_result)

    asyncio.run(scenario())


def test_private_client_applies_passthrough_allowlist_in_spawned_gateway() -> None:
    async def scenario() -> None:
        connections = {
            "private": {
                "transport": "stdio",
                "command": sys.executable,
                "args": ["-m", "deepagents_mcp_demo.server"],
            }
        }
        tools = await create_private_mcp_client(
            connections,
            passthrough_tools=("get_products",),
        ).get_tools()
        product_result = await next(
            tool for tool in tools if tool.name == "get_products"
        ).ainvoke({})
        customer_result = await next(
            tool for tool in tools if tool.name == "get_customers"
        ).ainvoke({})

        assert "Products" in str(product_result)
        assert "raw_rows_shared" in str(product_result)
        assert "Customers" not in str(customer_result)
        assert '"raw_data_shared":false' in str(customer_result)

    asyncio.run(scenario())