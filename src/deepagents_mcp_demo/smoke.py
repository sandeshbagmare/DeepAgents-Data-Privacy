from __future__ import annotations

import asyncio
import json

from deepagents_mcp_demo.mcp_client import create_mcp_client


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
    serialized = json.dumps(result, default=str)
    if '"rows"' in serialized or '"raw_rows_shared":true' in serialized.replace(" ", ""):
        raise RuntimeError("Privacy check failed: raw MCP rows reached the client")
    print("\nPrivate get_products aggregate result:")
    print(json.dumps(result, indent=2, default=str))


def main() -> None:
    asyncio.run(run_smoke_test())


if __name__ == "__main__":
    main()
