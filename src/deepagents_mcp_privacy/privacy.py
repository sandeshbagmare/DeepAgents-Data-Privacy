from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from numbers import Real
from typing import Any

import mcp.types as mt
from fastmcp.server import create_proxy
from fastmcp.server.middleware.middleware import CallNext, Middleware, MiddlewareContext
from fastmcp.tools.base import ToolResult

TextSanitizer = Callable[[str], str | Mapping[str, Any]]


@dataclass(frozen=True)
class PrivacyPolicy:
    minimum_cohort_size: int = 5
    expose_counts: bool = False
    expose_aggregates: bool = False
    row_keys: tuple[str, ...] = ("rows", "records", "items", "data")
    identifier_fields: tuple[str, ...] = (
        "id",
        "name",
        "email",
        "phone",
        "address",
        "token",
        "secret",
    )
    text_sanitizers: Mapping[str, TextSanitizer] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.minimum_cohort_size < 2:
            raise ValueError("minimum_cohort_size must be at least 2")


def sanitize_value(
    value: Any,
    *,
    policy: PrivacyPolicy | None = None,
    tool_name: str = "",
) -> dict[str, Any]:
    active_policy = policy or PrivacyPolicy()
    normalized = _normalize_value(value)
    if isinstance(normalized, str):
        sanitizer = active_policy.text_sanitizers.get(tool_name)
        if sanitizer is None:
            return _envelope(
                kind="text",
                safe={"withheld": True, "reason": "Unstructured text is withheld by default"},
            )
        normalized = _normalize_value(sanitizer(normalized))

    rows = _find_rows(normalized, active_policy.row_keys)
    if rows is not None:
        return _sanitize_rows(rows, active_policy)
    return _sanitize_structure(normalized, active_policy)


def _normalize_value(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def _find_rows(value: Any, row_keys: Sequence[str]) -> list[Mapping[str, Any]] | None:
    if _is_row_list(value):
        return list(value)
    if not isinstance(value, Mapping):
        return None
    for key in row_keys:
        candidate = value.get(key)
        if _is_row_list(candidate):
            return list(candidate)
    return None


def _is_row_list(value: Any) -> bool:
    return isinstance(value, list) and bool(value) and all(isinstance(item, Mapping) for item in value)


def _sanitize_rows(rows: list[Mapping[str, Any]], policy: PrivacyPolicy) -> dict[str, Any]:
    columns = sorted({str(key) for row in rows for key in row})
    field_types = {
        column: sorted({_type_name(row[column]) for row in rows if column in row})
        for column in columns
    }
    example = {column: _dummy_value(column, field_types[column], policy) for column in columns}
    result: dict[str, Any] = {}
    if policy.expose_counts:
        result["count"] = len(rows)
    if policy.expose_aggregates and len(rows) >= policy.minimum_cohort_size:
        numeric_fields = [
            column
            for column in columns
            if not _is_identifier(column, policy)
            and all(isinstance(row.get(column), Real) and not isinstance(row.get(column), bool) for row in rows)
        ]
        result["numeric_aggregates"] = {
            column: {
                "sum": round(sum(float(row[column]) for row in rows), 2),
                "average": round(sum(float(row[column]) for row in rows) / len(rows), 2),
                "minimum": min(float(row[column]) for row in rows),
                "maximum": max(float(row[column]) for row in rows),
            }
            for column in numeric_fields
        }
        categorical_fields = [
            column
            for column in columns
            if not _is_identifier(column, policy)
            and all(isinstance(row.get(column), (str, bool)) for row in rows)
        ]
        result["category_counts"] = {}
        for column in categorical_fields:
            counts = Counter(str(row[column]) for row in rows)
            if len(counts) <= 20:
                result["category_counts"][column] = {
                    f"SYNTHETIC_GROUP_{index}": count
                    if count >= policy.minimum_cohort_size
                    else None
                    for index, (_, count) in enumerate(sorted(counts.items()), start=1)
                }
    elif policy.expose_aggregates:
        result["numeric_aggregates"] = {
            "suppressed": True,
            "reason": f"Fewer than {policy.minimum_cohort_size} records were returned",
        }
    return _envelope(
        kind="table",
        safe={
            "schema": {"columns": columns, "types": field_types},
            "example_row": example,
            "result": result or {"withheld": True, "reason": "Schema-only policy is active"},
        },
        policy=policy,
    )


def _sanitize_structure(value: Any, policy: PrivacyPolicy) -> dict[str, Any]:
    return _envelope(
        kind="structured",
        safe={"shape": _shape(value, policy)},
        policy=policy,
    )


def _shape(value: Any, policy: PrivacyPolicy) -> Any:
    if isinstance(value, Mapping):
        return {
            _safe_field_name(str(key), index): {"withheld": True, "type": _type_name(item)}
            if _is_identifier(str(key), policy)
            else _shape(item, policy)
            for index, (key, item) in enumerate(value.items(), start=1)
        }
    if isinstance(value, list):
        shape: dict[str, Any] = {
            "type": "array",
            "items": _shape(value[0], policy) if value else None,
        }
        if policy.expose_counts:
            shape["length"] = len(value)
        return shape
    return {"type": _type_name(value), "example": _dummy_scalar(value)}


def _dummy_value(column: str, types: Sequence[str], policy: PrivacyPolicy) -> Any:
    if _is_identifier(column, policy):
        return "SYNTHETIC"
    if "number" in types:
        return 0
    if "boolean" in types:
        return False
    if "null" in types and len(types) == 1:
        return None
    return f"EXAMPLE_{column.upper()}"


def _dummy_scalar(value: Any) -> Any:
    if isinstance(value, bool):
        return False
    if isinstance(value, Real):
        return 0
    if value is None:
        return None
    return "SYNTHETIC"


def _type_name(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, Real):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, Mapping):
        return "object"
    return type(value).__name__


def _is_identifier(field: str, policy: PrivacyPolicy) -> bool:
    normalized = field.casefold().replace("-", "_")
    tokens = set(normalized.split("_"))
    return any(
        identifier.casefold() == normalized or identifier.casefold() in tokens
        for identifier in policy.identifier_fields
    )


def _safe_field_name(field: str, index: int) -> str:
    if _looks_like_schema_name(field):
        return field
    return f"SYNTHETIC_FIELD_{index}"


def _looks_like_schema_name(field: str) -> bool:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.-]{0,63}", field):
        return False
    if "@" in field or "://" in field:
        return False
    if re.fullmatch(r"(?:\d{1,3}\.){3}\d{1,3}", field):
        return False
    if re.fullmatch(r"[0-9a-fA-F]{8}-[0-9a-fA-F-]{27,}", field):
        return False
    return True


def _envelope(
    *,
    kind: str,
    safe: Mapping[str, Any],
    policy: PrivacyPolicy | None = None,
) -> dict[str, Any]:
    active_policy = policy or PrivacyPolicy()
    return {
        "privacy": {
            "raw_data_shared": False,
            "synthetic_examples_only": True,
            "policy": "deepagents-mcp-privacy",
            "minimum_cohort_size": active_policy.minimum_cohort_size,
        },
        "source_kind": kind,
        **safe,
    }


class PrivacyMiddleware(Middleware):
    def __init__(self, policy: PrivacyPolicy | None = None) -> None:
        self.policy = policy or PrivacyPolicy()

    async def on_call_tool(
        self,
        context: MiddlewareContext[mt.CallToolRequestParams],
        call_next: CallNext[mt.CallToolRequestParams, ToolResult],
    ) -> ToolResult:
        try:
            result = await call_next(context)
            if result.is_error:
                return _private_error()
            value = result.structured_content
            if value is None:
                texts = [block.text for block in result.content if isinstance(block, mt.TextContent)]
                value = texts[0] if len(texts) == 1 else texts
            sanitized = sanitize_value(value, policy=self.policy, tool_name=context.message.name)
            return ToolResult(
                content=[mt.TextContent(type="text", text=json.dumps(sanitized, separators=(",", ":")))],
                structured_content=sanitized,
                meta={},
            )
        except Exception:
            return _private_error()


def _private_error() -> ToolResult:
    safe_payload = {"error": "Upstream tool call failed; details withheld by privacy policy"}
    return ToolResult(
        content=[mt.TextContent(type="text", text=json.dumps(safe_payload, separators=(",", ":")))],
        structured_content=safe_payload,
        meta={},
        is_error=True,
    )


def create_private_proxy(
    upstream: Any,
    *,
    policy: PrivacyPolicy | None = None,
    name: str = "Private MCP Gateway",
) -> Any:
    proxy = create_proxy(upstream, name=name)
    proxy.add_middleware(PrivacyMiddleware(policy))
    return proxy