from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from langchain_mcp_adapters.client import MultiServerMCPClient


def server_config() -> dict[str, dict[str, Any]]:
    server_path = Path(__file__).with_name("server.py").resolve()
    return {
        "table_data": {
            "transport": "stdio",
            "command": sys.executable,
            "args": [str(server_path)],
        }
    }


def create_mcp_client() -> MultiServerMCPClient:
    return MultiServerMCPClient(server_config())
