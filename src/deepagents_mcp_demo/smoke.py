from __future__ import annotations

import asyncio
import json

from deepagents_mcp_demo.mcp_client import create_mcp_client


def parse_tool_payload(result: object) -> dict[str, object]:
    if not isinstance(result, list) or len(result) != 1:
        raise RuntimeError("Expected one MCP content block")
    block = result[0]
    if not isinstance(block, dict) or block.get("type") != "text":
        raise RuntimeError("Expected one MCP text content block")
    payload = json.loads(str(block.get("text", "")))
    if not isinstance(payload, dict):
        raise RuntimeError("Expected the MCP tool to return a JSON object")
    return payload


def assert_private_payload(payload: dict[str, object]) -> None:
    def contains_forbidden_key(value: object) -> bool:
        if isinstance(value, dict):
            return "rows" in value or any(contains_forbidden_key(item) for item in value.values())
        if isinstance(value, list):
            return any(contains_forbidden_key(item) for item in value)
        return False

    if contains_forbidden_key(payload):
        raise RuntimeError("Privacy check failed: raw MCP rows reached the client")
    privacy = payload.get("privacy")
    if not isinstance(privacy, dict) or privacy.get("raw_rows_shared") is not False:
        raise RuntimeError("Privacy check failed: response lacks the no-raw-rows guarantee")
    example = payload.get("example_row")
    if not isinstance(example, dict) or example.get("id") != "EXAMPLE-0000":
        raise RuntimeError("Privacy check failed: example row is not synthetic")


async def run_smoke_test() -> None:
    tools = await create_mcp_client().get_tools()
    print(f"Connected to MCP server: {len(tools)} tools")
    print(", ".join(tool.name for tool in tools))

    if len(tools) != 34:
        raise RuntimeError(f"Expected 34 tools, received {len(tools)}")

    products_tool = next(tool for tool in tools if tool.name == "get_products")
    result = await products_tool.ainvoke(
        {"operation": "group_average", "group_by": "category", "seed": 7}
    )
    assert_private_payload(parse_tool_payload(result))
    print("\nPrivate get_products aggregate result:")
    print(json.dumps(result, indent=2, default=str))


def main() -> None:
    asyncio.run(run_smoke_test())


if __name__ == "__main__":
    main()
