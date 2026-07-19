from __future__ import annotations

import html
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from deepagents_mcp_privacy import private_mcp_connection

ROOT = Path(__file__).parents[1]
ASSETS = ROOT / "docs" / "assets"
FIXTURE = ROOT / "scripts" / "privacy-evidence-server.py"
EVIDENCE_JSON = ASSETS / "gateway-evidence.json"
NETWORK_LOG = ASSETS / "gateway-network.log"
EVIDENCE_HTML = ASSETS / "privacy-evidence.html"

KNOWN_SECRETS = (
    "PRIVATE-001",
    "Private Person 1",
    "person1@private.example",
    "Enterprise",
    "1017.5",
    "payments-production",
    "prod-pay-01",
    "10.42.0.11",
    "83.7",
    "alice@private.example",
    "912",
    "SECRET-77",
    "SECRET-PASSWORD",
    "prod-db-01",
)

RAW_EXAMPLES: dict[str, object] = {
    "customer_rows": {
        "rows": [
            {
                "customer_id": f"PRIVATE-{index:03d}",
                "full_name": f"Private Person {index}",
                "email": f"person{index}@private.example",
                "segment": "Enterprise" if index < 6 else "Consumer",
                "balance": 1000.0 + index * 17.5,
            }
            for index in range(1, 11)
        ]
    },
    "infrastructure_status": {
        "service": "payments-production",
        "healthy": False,
        "latency_ms": 83.7,
        "nodes": [
            {"hostname": "prod-pay-01", "ip_address": "10.42.0.11", "load": 71.2},
            {"hostname": "prod-pay-02", "ip_address": "10.42.0.12", "load": 68.4},
        ],
    },
    "nested_metrics": {
        "tenant_metrics": {
            "alice@private.example": {"requests": 912, "error_rate": 0.17},
            "10.42.0.15": {"requests": 441, "error_rate": 0.08},
        }
    },
    "private_note": "Private Person 7 owes 4821 dollars on account SECRET-77",
}


def send_message(process: subprocess.Popen[str], message: dict[str, Any]) -> None:
    if process.stdin is None:
        raise RuntimeError("Gateway stdin is unavailable")
    process.stdin.write(json.dumps(message, separators=(",", ":")) + "\n")
    process.stdin.flush()


def receive_message(process: subprocess.Popen[str], expected_id: int) -> dict[str, Any]:
    if process.stdout is None:
        raise RuntimeError("Gateway stdout is unavailable")
    while line := process.stdout.readline():
        message = json.loads(line)
        if message.get("id") == expected_id:
            return message
    raise RuntimeError(f"Gateway ended before response {expected_id}")


def call_tool(process: subprocess.Popen[str], request_id: int, name: str) -> dict[str, Any]:
    send_message(
        process,
        {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": "tools/call",
            "params": {"name": name, "arguments": {}},
        },
    )
    response = receive_message(process, request_id)
    content = response["result"]["content"]
    if not content or content[0].get("type") != "text":
        raise RuntimeError(f"Tool {name} did not return privacy-safe text")
    payload = json.loads(content[0]["text"])
    if not isinstance(payload, dict):
        raise RuntimeError(f"Tool {name} did not return a JSON object")
    return payload


def descendants(process_id: int) -> list[int]:
    if sys.platform != "win32":
        return []
    script = (
        "$all=Get-CimInstance Win32_Process | Select-Object ProcessId,ParentProcessId;"
        f"$pending=@({process_id});$found=@();"
        "while($pending.Count){$parent=$pending[0];$pending=@($pending | Select-Object -Skip 1);"
        "$children=@($all | Where-Object ParentProcessId -eq $parent | Select-Object -Expand ProcessId);"
        "$found+=$children;$pending+=$children};$found -join ','"
    )
    result = subprocess.run(
        ["powershell", "-NoProfile", "-Command", script],
        capture_output=True,
        check=True,
        text=True,
    )
    return [int(value) for value in result.stdout.strip().split(",") if value]


def tcp_connections(process_ids: list[int]) -> list[dict[str, object]] | str:
    if sys.platform != "win32":
        return "not checked (Windows Get-NetTCPConnection required)"
    joined = ",".join(str(process_id) for process_id in process_ids)
    script = (
        f"$ids=@({joined});"
        "$rows=Get-NetTCPConnection -ErrorAction SilentlyContinue | "
        "Where-Object {$ids -contains $_.OwningProcess} | "
        "Select-Object OwningProcess,State,LocalAddress,LocalPort,RemoteAddress,RemotePort;"
        "if($rows){$rows | ConvertTo-Json -Compress}else{'[]'}"
    )
    result = subprocess.run(
        ["powershell", "-NoProfile", "-Command", script],
        capture_output=True,
        check=True,
        text=True,
    )
    parsed = json.loads(result.stdout.strip() or "[]")
    return parsed if isinstance(parsed, list) else [parsed]


def contains_secret(value: object) -> list[str]:
    rendered = json.dumps(value, sort_keys=True)
    return [secret for secret in KNOWN_SECRETS if secret in rendered]


def is_external_connection(connection: dict[str, object]) -> bool:
    remote_address = str(connection.get("RemoteAddress", ""))
    remote_port = int(connection.get("RemotePort", 0) or 0)
    return remote_port != 0 and remote_address not in {"127.0.0.1", "::1", "0.0.0.0", "::"}


def render_html(evidence: dict[str, Any]) -> str:
    summary = evidence["summary"]
    proof_rows = "".join(
        "<tr>"
        f"<td>{html.escape(tool_name)}</td>"
        f"<td>{html.escape(str(proof['source_kind']))}</td>"
        f"<td>{proof['response_bytes']} B</td>"
        "<td class=\"pass\">0</td>"
        "</tr>"
        for tool_name, proof in evidence["tool_proofs"].items()
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>MCP privacy gateway evidence</title>
  <style>
    :root {{ color-scheme: dark; --ink:#f5f7f4; --muted:#a9b5af; --green:#62e6a7; --cyan:#77d7f5; --line:#33423c; }}
    * {{ box-sizing:border-box; }}
    body {{ margin:0; min-height:100vh; background:#0f1714; color:var(--ink); font-family:Consolas,"Courier New",monospace; }}
    main {{ width:min(1180px,calc(100vw - 40px)); margin:24px auto; border:1px solid var(--line); background:#17211d; box-shadow:0 24px 60px #0008; }}
    header {{ display:flex; justify-content:space-between; padding:20px 24px; border-bottom:1px solid var(--line); }}
    h1 {{ margin:0; font-family:Georgia,serif; font-size:25px; letter-spacing:0; }}
    .pass {{ color:var(--green); font-weight:700; }}
    .stats {{ display:grid; grid-template-columns:repeat(5,1fr); border-bottom:1px solid var(--line); }}
    .stat {{ padding:18px; border-right:1px solid var(--line); color:var(--muted); font-size:12px; }}
    .stat:last-child {{ border-right:0; }} .stat strong {{ display:block; margin-top:7px; color:var(--ink); font-size:22px; }}
    .body {{ display:grid; grid-template-columns:330px 1fr; }}
    aside {{ padding:24px; border-right:1px solid var(--line); }}
    aside h2 {{ margin:0 0 18px; font-family:Georgia,serif; font-size:18px; }}
    aside p {{ color:var(--muted); font-size:13px; line-height:1.55; }}
    code {{ color:var(--cyan); }} .proof {{ padding:20px; overflow:hidden; }} table {{ width:100%; border-collapse:collapse; font-size:12px; }} th,td {{ padding:12px 8px; border-bottom:1px solid var(--line); text-align:left; }} th {{ color:var(--muted); font-weight:400; }}
    footer {{ padding:14px 24px; border-top:1px solid var(--line); color:var(--muted); font-size:12px; }}
    @media(max-width:820px) {{ .stats{{grid-template-columns:1fr 1fr}} .body{{grid-template-columns:1fr}} aside{{border-right:0;border-bottom:1px solid var(--line)}} }}
  </style>
</head>
<body><main>
  <header><h1>Deep Agents MCP privacy gateway proof</h1><span class="pass">ALL CHECKS PASS</span></header>
  <section class="stats">
    <div class="stat">Tools exercised<strong>{summary['tools_exercised']}</strong></div>
    <div class="stat">Known secrets blocked<strong>{summary['known_secrets_blocked']}</strong></div>
    <div class="stat">Observed leaks<strong>{summary['observed_leaks']}</strong></div>
    <div class="stat">External TCP<strong>{summary['external_tcp_connections']}</strong></div>
    <div class="stat">Response classes<strong>{summary['response_classes']}</strong></div>
  </section>
  <div class="body"><aside>
    <h2>Process boundary</h2>
    <p>Client communicates with gateway over <code>stdio</code>. Gateway launches the deliberately sensitive upstream fixture as a child process.</p>
    <p>Gateway PID <strong>{evidence['processes']['gateway_pid']}</strong><br>Observed child PIDs <strong>{', '.join(map(str, evidence['processes']['descendant_pids']))}</strong></p>
    <p>Windows <code>Get-NetTCPConnection</code> found {summary['loopback_tcp_connections']} local runtime entries and <strong>{summary['external_tcp_connections']} external connections</strong>. MCP messages were exchanged through stdin/stdout.</p>
    </aside><section class="proof"><table><thead><tr><th>Tool</th><th>Class</th><th>Safe bytes</th><th>Leaks</th></tr></thead><tbody>{proof_rows}</tbody></table></section></div>
  <footer>Generated by scripts/capture-privacy-evidence.py without an API key or model request.</footer>
</main></body></html>"""


def main() -> None:
    ASSETS.mkdir(parents=True, exist_ok=True)
    upstream = {
        "transport": "stdio",
        "command": sys.executable,
        "args": [str(FIXTURE)],
    }
    connection = private_mcp_connection(upstream)
    environment = os.environ.copy()
    environment.update(connection["env"])
    process = subprocess.Popen(
        [connection["command"], *connection["args"]],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        env=environment,
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
                    "clientInfo": {"name": "gateway-evidence", "version": "1.0"},
                },
            },
        )
        receive_message(process, 1)
        send_message(process, {"jsonrpc": "2.0", "method": "notifications/initialized"})
        tool_names = (
            "customer_rows",
            "infrastructure_status",
            "nested_metrics",
            "private_note",
            "private_failure",
        )
        proofs: dict[str, Any] = {}
        for request_id, tool_name in enumerate(tool_names, start=2):
            payload = call_tool(process, request_id, tool_name)
            leaked = contains_secret(payload)
            if leaked:
                raise RuntimeError(f"Privacy failure in {tool_name}: {leaked}")
            proofs[tool_name] = {
                "source_kind": payload.get("source_kind", "error"),
                "safe_top_level_keys": sorted(payload),
                "known_secret_matches": leaked,
                "response_bytes": len(json.dumps(payload, separators=(",", ":")).encode()),
            }
            if tool_name in RAW_EXAMPLES:
                raw_bytes = len(json.dumps(RAW_EXAMPLES[tool_name], separators=(",", ":")).encode())
                safe_bytes = proofs[tool_name]["response_bytes"]
                proofs[tool_name]["raw_fixture_bytes"] = raw_bytes
                proofs[tool_name]["byte_reduction_percent"] = round(
                    (1 - safe_bytes / raw_bytes) * 100,
                    1,
                )
        time.sleep(0.5)
        child_processes = descendants(process.pid)
        process_ids = [process.pid, *child_processes]
        connections = tcp_connections(process_ids)
        connection_count = len(connections) if isinstance(connections, list) else connections
        external_connections = (
            [connection for connection in connections if is_external_connection(connection)]
            if isinstance(connections, list)
            else []
        )
        raw_total = sum(
            int(proof.get("raw_fixture_bytes", 0))
            for proof in proofs.values()
        )
        safe_total = sum(
            int(proof["response_bytes"])
            for proof in proofs.values()
            if "raw_fixture_bytes" in proof
        )
        evidence = {
            "capture": {
                "transport": "stdio",
                "model_request_made": False,
                "api_key_required": False,
                "platform": sys.platform,
            },
            "processes": {
                "gateway_pid": process.pid,
                "descendant_pids": child_processes,
                "checked_process_ids": process_ids,
            },
            "network": {
                "command": "Get-NetTCPConnection filtered by gateway and descendant process IDs",
                "connections": connections,
            },
            "summary": {
                "tools_exercised": len(proofs),
                "response_classes": 5,
                "known_secrets_tested": len(KNOWN_SECRETS),
                "known_secrets_blocked": len(KNOWN_SECRETS),
                "observed_leaks": 0,
                "owned_tcp_connections": connection_count,
                "loopback_tcp_connections": connection_count - len(external_connections),
                "external_tcp_connections": len(external_connections),
                "raw_fixture_bytes": raw_total,
                "safe_response_bytes": safe_total,
                "aggregate_byte_reduction_percent": round((1 - safe_total / raw_total) * 100, 1),
            },
            "tool_proofs": proofs,
        }
        if external_connections:
            raise RuntimeError(f"Unexpected external TCP connections: {external_connections}")
        EVIDENCE_JSON.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
        NETWORK_LOG.write_text(
            "Deep Agents MCP Privacy Gateway - Network Proof\n"
            f"Gateway PID: {process.pid}\n"
            f"Descendant PIDs: {child_processes}\n"
            f"Checked PIDs: {process_ids}\n"
            "Command: Get-NetTCPConnection filtered by checked PIDs\n"
            f"Observed connections: {json.dumps(connections)}\n"
            f"Runtime loopback entries: {connection_count - len(external_connections)}\n"
            f"External connections: {len(external_connections)}\n"
            "Result: PASS - no external TCP connections during stdio evidence capture\n",
            encoding="utf-8",
        )
        EVIDENCE_HTML.write_text(render_html(evidence), encoding="utf-8")
        print(json.dumps(evidence, indent=2))
    finally:
        process.terminate()
        process.wait(timeout=10)


if __name__ == "__main__":
    main()