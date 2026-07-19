from __future__ import annotations

import base64
import json
import os
import sys
from collections.abc import Mapping
from typing import Any

from deepagents_mcp_privacy.privacy import PrivacyPolicy, create_private_proxy

CONFIG_ENV = "DEEPAGENTS_MCP_PRIVACY_CONFIG"
POLICY_ENV = "DEEPAGENTS_MCP_PRIVACY_POLICY"


def private_mcp_connection(
    upstream: Mapping[str, Any],
    *,
    minimum_cohort_size: int = 5,
    expose_counts: bool = False,
    expose_aggregates: bool = False,
    identifier_fields: tuple[str, ...] | None = None,
) -> dict[str, Any]:
    if minimum_cohort_size < 2:
        raise ValueError("minimum_cohort_size must be at least 2")
    policy: dict[str, Any] = {
        "minimum_cohort_size": minimum_cohort_size,
        "expose_counts": expose_counts,
        "expose_aggregates": expose_aggregates,
    }
    if identifier_fields is not None:
        policy["identifier_fields"] = list(identifier_fields)
    environment = {
        CONFIG_ENV: _encode_json(_to_fastmcp_config(upstream)),
        POLICY_ENV: _encode_json(policy),
    }
    return {
        "transport": "stdio",
        "command": sys.executable,
        "args": ["-m", "deepagents_mcp_privacy.runner"],
        "env": environment,
    }


def create_private_mcp_client(
    connections: Mapping[str, Mapping[str, Any]],
    *,
    minimum_cohort_size: int = 5,
    expose_counts: bool = False,
    expose_aggregates: bool = False,
    identifier_fields: tuple[str, ...] | None = None,
) -> Any:
    from langchain_mcp_adapters.client import MultiServerMCPClient

    private_connections = {
        name: private_mcp_connection(
            connection,
            minimum_cohort_size=minimum_cohort_size,
            expose_counts=expose_counts,
            expose_aggregates=expose_aggregates,
            identifier_fields=identifier_fields,
        )
        for name, connection in connections.items()
    }
    return MultiServerMCPClient(private_connections)


def _to_fastmcp_config(connection: Mapping[str, Any]) -> dict[str, Any]:
    server = dict(connection)
    transport = server.get("transport")
    if transport == "streamable_http":
        server["transport"] = "http"
    server.pop("session_kwargs", None)
    server.pop("encoding", None)
    server.pop("encoding_error_handler", None)
    return {"mcpServers": {"upstream": server}}


def _encode_json(value: Mapping[str, Any]) -> str:
    serialized = json.dumps(value, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(serialized).decode("ascii")


def _decode_json(value: str) -> dict[str, Any]:
    decoded = base64.urlsafe_b64decode(value.encode("ascii"))
    result = json.loads(decoded)
    if not isinstance(result, dict):
        raise ValueError("Gateway configuration must be a JSON object")
    return result


def main() -> None:
    encoded_config = os.getenv(CONFIG_ENV)
    if not encoded_config:
        raise SystemExit(f"{CONFIG_ENV} is required")
    config = _decode_json(encoded_config)
    policy_data = _decode_json(os.getenv(POLICY_ENV, _encode_json({})))
    policy = PrivacyPolicy(**policy_data)
    create_private_proxy(config, policy=policy).run(transport="stdio")


if __name__ == "__main__":
    main()