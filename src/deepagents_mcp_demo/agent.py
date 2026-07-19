from __future__ import annotations

import argparse
import asyncio
import os

from deepagents import create_deep_agent
from dotenv import load_dotenv

from deepagents_mcp_demo.mcp_client import create_mcp_client


async def run_agent(question: str) -> None:
    load_dotenv()
    model = os.getenv("MODEL")
    if not model:
        raise SystemExit("Set MODEL in .env, for example openai:gpt-4.1-mini")

    tools = await create_mcp_client().get_tools()
    agent = create_deep_agent(
        model=model,
        tools=tools,
        system_prompt=(
            "You are a privacy-preserving data analyst. MCP tools compute over raw data "
            "inside the server and return only aggregates, schema, and one synthetic "
            "example. Never claim the example is a real record. Answer using aggregate "
            "results, call tools again with filters or grouping when needed, and mention "
            "which tool and operation supplied each result. If a question requires an "
            "individual raw record, explain that the privacy boundary does not expose it."
        ),
    )
    result = await agent.ainvoke(
        {"messages": [{"role": "user", "content": question}]}
    )
    print(result["messages"][-1].content)


def main() -> None:
    parser = argparse.ArgumentParser(description="Ask the MCP-connected Deep Agent")
    parser.add_argument(
        "question",
        nargs="?",
        default="Summarize products and compare average price by category.",
    )
    args = parser.parse_args()
    asyncio.run(run_agent(args.question))


if __name__ == "__main__":
    main()
