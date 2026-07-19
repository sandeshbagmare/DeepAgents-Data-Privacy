from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


def send_message(process: subprocess.Popen[str], message: dict[str, Any]) -> None:
    if process.stdin is None:
        raise RuntimeError("MCP process stdin is unavailable")
    process.stdin.write(json.dumps(message, separators=(",", ":")) + "\n")
    process.stdin.flush()


def receive_message(process: subprocess.Popen[str], expected_id: int) -> dict[str, Any]:
    if process.stdout is None:
        raise RuntimeError("MCP process stdout is unavailable")
    while line := process.stdout.readline():
        message = json.loads(line)
        if message.get("id") == expected_id:
            return message
    error = process.stderr.read() if process.stderr else ""
    raise RuntimeError(f"MCP process ended before response {expected_id}: {error}")


def count_tcp_connections(process_id: int) -> int | str:
    if sys.platform != "win32":
        return "not checked (Windows Get-NetTCPConnection required)"
    command = f"@(Get-NetTCPConnection -OwningProcess {process_id} -ErrorAction SilentlyContinue).Count"
    result = subprocess.run(
        ["powershell", "-NoProfile", "-Command", command],
        capture_output=True,
        check=True,
        text=True,
    )
    return int(result.stdout.strip() or "0")


def contains_rows_key(value: object) -> bool:
    if isinstance(value, dict):
        return "rows" in value or any(contains_rows_key(item) for item in value.values())
    if isinstance(value, list):
        return any(contains_rows_key(item) for item in value)
    return False


def main() -> None:
    server = Path(__file__).parents[1] / "src" / "deepagents_mcp_demo" / "server.py"
    process = subprocess.Popen(
        [sys.executable, str(server.resolve())],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )
    try:
        send_message(
            process,
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "privacy-evidence", "version": "1.0"},
                },
            },
        )
        receive_message(process, 1)
        send_message(process, {"jsonrpc": "2.0", "method": "notifications/initialized"})
        send_message(
            process,
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {
                    "name": "get_products",
                    "arguments": {
                        "operation": "group_average",
                        "group_by": "category",
                        "seed": 7,
                    },
                },
            },
        )
        response = receive_message(process, 2)
        payload = json.loads(response["result"]["content"][0]["text"])
        if contains_rows_key(payload):
            raise RuntimeError("Privacy check failed: MCP response contains a rows key")
        if payload.get("privacy", {}).get("raw_rows_shared") is not False:
            raise RuntimeError("Privacy check failed: no-raw-rows guarantee is missing")
        if payload.get("example_row", {}).get("id") != "EXAMPLE-0000":
            raise RuntimeError("Privacy check failed: example row is not synthetic")
        time.sleep(0.25)
        evidence = {
            "mcp_transport": "stdio",
            "tool": "get_products",
            "operation": "group_average",
            "server_tcp_connections": count_tcp_connections(process.pid),
            "response_top_level_keys": list(payload),
            "raw_rows_shared": payload["privacy"]["raw_rows_shared"],
            "example_is_synthetic": payload["privacy"]["example_is_synthetic"],
            "result": payload["result"],
        }
        print(json.dumps(evidence, indent=2))
    finally:
        process.terminate()
        process.wait(timeout=5)


if __name__ == "__main__":
    main()