from __future__ import annotations

import html
import json
import os
import subprocess
import sys
import time
from datetime import UTC, datetime
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
        f"<td><strong>{html.escape(tool_name)}</strong></td>"
        f"<td><span class=\"type\">{html.escape(str(proof['source_kind']))}</span></td>"
        f"<td>{proof['response_bytes']} B</td>"
        "<td><span class=\"zero\">0</span></td>"
        "</tr>"
        for tool_name, proof in evidence["tool_proofs"].items()
    )
    captured_at = html.escape(str(evidence["capture"]["generated_at_utc"]))
    gateway_pid = evidence["processes"]["gateway_pid"]
    descendant_pids = ", ".join(map(str, evidence["processes"]["descendant_pids"]))
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
    <meta name="description" content="Reproducible proof that MCP tools process complete data while the LLM receives only safe structural output.">
    <title>Deep Agents MCP privacy proof</title>
  <style>
        :root {{
            color-scheme: dark;
            --canvas:#0b0e0d;
            --surface:#121714;
            --surface-2:#18201c;
            --paper:#edf2ec;
            --muted:#9daaa3;
            --line:#314039;
            --mint:#70e2aa;
            --cyan:#7bd7ed;
            --amber:#f2c66d;
            --coral:#ff8d78;
        }}
    * {{ box-sizing:border-box; }}
        html {{ scroll-behavior:smooth; }}
        body {{ margin:0; min-height:100vh; background:var(--canvas); color:var(--paper); font-family:"Segoe UI",Tahoma,sans-serif; letter-spacing:0; }}
        body::before {{ content:""; position:fixed; inset:0; pointer-events:none; opacity:.22; background-image:linear-gradient(#253029 1px,transparent 1px),linear-gradient(90deg,#253029 1px,transparent 1px); background-size:40px 40px; mask-image:linear-gradient(to bottom,#000,transparent 70%); }}
        a {{ color:inherit; }}
        button,a.button {{ min-height:40px; display:inline-flex; align-items:center; justify-content:center; gap:8px; border:1px solid var(--line); border-radius:6px; padding:0 14px; background:var(--surface-2); color:var(--paper); font:600 12px Consolas,"Courier New",monospace; text-decoration:none; cursor:pointer; }}
        button:hover,a.button:hover {{ border-color:var(--mint); color:var(--mint); }}
        button:focus-visible,a:focus-visible {{ outline:2px solid var(--cyan); outline-offset:3px; }}
        .primary {{ background:var(--mint)!important; color:#07100b!important; border-color:var(--mint)!important; }}
        .shell {{ position:relative; width:min(1240px,calc(100vw - 40px)); margin:0 auto; }}
        nav {{ height:72px; display:flex; align-items:center; justify-content:space-between; border-bottom:1px solid var(--line); }}
        .brand {{ display:flex; align-items:center; gap:12px; font:700 13px Consolas,"Courier New",monospace; }}
        .mark {{ width:32px; height:32px; display:grid; place-items:center; border:1px solid var(--mint); color:var(--mint); font-size:15px; }}
        .nav-actions {{ display:flex; gap:8px; }}
        .hero {{ min-height:540px; display:grid; grid-template-columns:minmax(0,1.15fr) minmax(360px,.85fr); gap:58px; align-items:center; padding:64px 0 72px; }}
        .eyebrow {{ margin:0 0 18px; color:var(--mint); font:700 12px Consolas,"Courier New",monospace; text-transform:uppercase; }}
        h1 {{ max-width:760px; margin:0; font-family:Georgia,"Times New Roman",serif; font-size:clamp(44px,6vw,78px); font-weight:500; line-height:.98; letter-spacing:0; }}
        .lede {{ max-width:700px; margin:26px 0 30px; color:var(--muted); font-size:18px; line-height:1.65; }}
        .hero-actions {{ display:flex; flex-wrap:wrap; gap:10px; }}
        .terminal {{ border:1px solid var(--line); background:#080b09; box-shadow:14px 14px 0 #1e2923; }}
        .terminal-head {{ height:42px; display:flex; align-items:center; justify-content:space-between; padding:0 14px; border-bottom:1px solid var(--line); color:var(--muted); font:11px Consolas,"Courier New",monospace; }}
        .terminal-body {{ padding:22px; font:13px/1.8 Consolas,"Courier New",monospace; }}
        .prompt {{ color:var(--cyan); }} .ok {{ color:var(--mint); }} .quiet {{ color:var(--muted); }}
        .status-line {{ display:flex; align-items:center; gap:8px; color:var(--mint); font-weight:700; }}
        .status-dot {{ width:8px; height:8px; background:var(--mint); box-shadow:0 0 18px var(--mint); }}
        .stats {{ display:grid; grid-template-columns:repeat(5,1fr); border:1px solid var(--line); background:var(--surface); }}
        .stat {{ min-height:126px; padding:22px; border-right:1px solid var(--line); color:var(--muted); font:11px Consolas,"Courier New",monospace; text-transform:uppercase; }}
        .stat:last-child {{ border-right:0; }}
        .stat strong {{ display:block; margin-top:16px; color:var(--paper); font:500 35px Georgia,"Times New Roman",serif; }}
        section.content {{ padding:92px 0; }}
        .section-head {{ display:flex; justify-content:space-between; gap:40px; align-items:end; margin-bottom:34px; }}
        h2 {{ margin:0; font:500 34px Georgia,"Times New Roman",serif; letter-spacing:0; }}
        .section-head p {{ max-width:560px; margin:0; color:var(--muted); line-height:1.6; }}
        .boundary {{ display:grid; grid-template-columns:1fr 120px 1fr; align-items:stretch; }}
        .boundary-card {{ border:1px solid var(--line); padding:28px; background:var(--surface); }}
        .boundary-card .label {{ color:var(--muted); font:11px Consolas,"Courier New",monospace; text-transform:uppercase; }}
        .boundary-card h3 {{ margin:12px 0 20px; font:500 24px Georgia,"Times New Roman",serif; }}
        .boundary-card ul {{ margin:0; padding:0; list-style:none; display:grid; gap:10px; color:var(--muted); font-size:14px; }}
        .boundary-card li::before {{ content:"+"; margin-right:9px; color:var(--mint); }}
        .gate {{ display:grid; place-items:center; border-top:1px solid var(--line); border-bottom:1px solid var(--line); color:var(--amber); font:700 11px/1.5 Consolas,"Courier New",monospace; text-align:center; }}
        .proof-grid {{ display:grid; grid-template-columns:340px 1fr; border:1px solid var(--line); background:var(--surface); }}
        .process {{ padding:28px; border-right:1px solid var(--line); }}
        .process h3 {{ margin:0 0 18px; font:500 22px Georgia,"Times New Roman",serif; }}
        .process p {{ color:var(--muted); font-size:13px; line-height:1.65; }}
        code {{ color:var(--cyan); font-family:Consolas,"Courier New",monospace; }}
        .pid {{ display:block; margin:18px 0; padding:14px; border-left:3px solid var(--cyan); background:#0d1210; color:var(--paper); font:12px/1.7 Consolas,"Courier New",monospace; overflow-wrap:anywhere; }}
        .proof {{ padding:12px 24px 20px; overflow-x:auto; }}
        table {{ width:100%; border-collapse:collapse; font-size:13px; }}
        th,td {{ padding:16px 10px; border-bottom:1px solid var(--line); text-align:left; }}
        th {{ color:var(--muted); font:400 11px Consolas,"Courier New",monospace; text-transform:uppercase; }}
        .type {{ color:var(--cyan); font-family:Consolas,"Courier New",monospace; }}
        .zero {{ display:inline-grid; min-width:30px; height:25px; place-items:center; border:1px solid #356b50; border-radius:4px; color:var(--mint); font:700 11px Consolas,"Courier New",monospace; }}
        .artifacts {{ display:grid; grid-template-columns:repeat(4,1fr); gap:12px; }}
        .artifact {{ min-height:150px; padding:22px; border:1px solid var(--line); background:var(--surface); text-decoration:none; }}
        .artifact:hover {{ border-color:var(--cyan); }}
        .artifact span {{ color:var(--cyan); font:11px Consolas,"Courier New",monospace; }}
        .artifact h3 {{ margin:18px 0 8px; font-size:16px; }}
        .artifact p {{ margin:0; color:var(--muted); font-size:13px; line-height:1.5; }}
        .runbook {{ display:grid; grid-template-columns:1fr 1fr; gap:14px; }}
        .run-step {{ display:grid; grid-template-columns:52px 1fr; gap:18px; padding:24px; border:1px solid var(--line); background:var(--surface); }}
        .step-number {{ width:42px; height:42px; display:grid; place-items:center; border:1px solid var(--amber); color:var(--amber); font:700 12px Consolas,"Courier New",monospace; }}
        .run-step h3 {{ margin:0 0 8px; font-size:16px; }} .run-step p {{ margin:0; color:var(--muted); font-size:13px; line-height:1.55; }}
        .command {{ display:flex; align-items:center; justify-content:space-between; gap:14px; margin-top:14px; padding:11px 12px; background:#080b09; color:var(--cyan); font:12px Consolas,"Courier New",monospace; overflow-wrap:anywhere; }}
        .command button {{ min-height:30px; padding:0 9px; flex:0 0 auto; }}
        footer {{ display:flex; justify-content:space-between; gap:24px; padding:26px 0 36px; border-top:1px solid var(--line); color:var(--muted); font:11px/1.6 Consolas,"Courier New",monospace; }}
        .toast {{ position:fixed; right:20px; bottom:20px; z-index:5; padding:12px 16px; border:1px solid var(--mint); background:#101914; color:var(--mint); font:12px Consolas,"Courier New",monospace; opacity:0; transform:translateY(10px); transition:.18s ease; pointer-events:none; }}
        .toast.show {{ opacity:1; transform:translateY(0); }}
        @media(max-width:920px) {{
            .hero {{ grid-template-columns:1fr; min-height:auto; }} .stats {{ grid-template-columns:repeat(2,1fr); }} .stat {{ border-bottom:1px solid var(--line); }}
            .boundary {{ grid-template-columns:1fr; }} .gate {{ min-height:80px; border-left:1px solid var(--line); border-right:1px solid var(--line); }}
            .proof-grid {{ grid-template-columns:1fr; }} .process {{ border-right:0; border-bottom:1px solid var(--line); }} .artifacts {{ grid-template-columns:1fr 1fr; }}
        }}
        @media(max-width:620px) {{
            .shell {{ width:min(100% - 24px,1240px); }} nav {{ height:auto; min-height:68px; align-items:flex-start; padding:16px 0; gap:14px; }} .brand span:last-child {{ display:none; }}
            .nav-actions {{ flex-wrap:wrap; justify-content:flex-end; }} .nav-actions .button:not(.primary) {{ display:none; }} h1 {{ font-size:42px; }} .hero {{ padding:46px 0 58px; gap:40px; }}
            .stats {{ grid-template-columns:1fr 1fr; }} .stat {{ min-height:105px; padding:16px; }} .stat strong {{ font-size:28px; }} section.content {{ padding:64px 0; }}
            .section-head {{ display:block; }} .section-head p {{ margin-top:14px; }} .artifacts,.runbook {{ grid-template-columns:1fr; }} footer {{ display:block; }}
        }}
        @media(prefers-reduced-motion:reduce) {{ html {{ scroll-behavior:auto; }} .toast {{ transition:none; }} }}
  </style>
</head>
<body>
    <div class="shell">
        <nav aria-label="Evidence navigation">
            <div class="brand"><span class="mark">DP</span><span>DEEP AGENTS / PRIVACY GATEWAY</span></div>
            <div class="nav-actions">
                <a class="button" href="../confluence-implementation-guide.md">Confluence guide</a>
                <a class="button primary" href="../../../RUN_DEMO.cmd">Run demo</a>
            </div>
        </nav>

        <header class="hero">
            <div>
                <p class="eyebrow">Reproducible MCP boundary evidence</p>
                <h1>Full data for tools. Safe context for models.</h1>
                <p class="lede">The upstream tool executes against complete authorized records. FastMCP middleware replaces its outbound result before the agent can observe it, leaving schema, types, and synthetic examples.</p>
                <div class="hero-actions">
                    <a class="button primary" href="#proof">Inspect the proof</a>
                    <button type="button" data-copy=".\\RUN_DEMO.cmd">Copy one-click command</button>
                </div>
            </div>
            <div class="terminal" aria-label="Demo execution result">
                <div class="terminal-head"><span>RUN_DEMO.cmd</span><span class="status-line"><span class="status-dot"></span>PASS</span></div>
                <div class="terminal-body">
                    <div><span class="prompt">&gt;</span> capture privacy evidence</div>
                    <div class="ok">[pass] upstream tools exercised: {summary['tools_exercised']}</div>
                    <div class="ok">[pass] selected canaries blocked: {summary['known_secrets_blocked']}/{summary['known_secrets_tested']}</div>
                    <div class="ok">[pass] observed value leaks: {summary['observed_leaks']}</div>
                    <div class="ok">[pass] external TCP connections: {summary['external_tcp_connections']}</div>
                    <div class="quiet">[info] model requests: 0 / API keys: none</div>
                </div>
            </div>
        </header>

        <section class="stats" aria-label="Evidence summary">
            <div class="stat">Tools exercised<strong>{summary['tools_exercised']}</strong></div>
            <div class="stat">Canaries blocked<strong>{summary['known_secrets_blocked']}</strong></div>
            <div class="stat">Observed leaks<strong>{summary['observed_leaks']}</strong></div>
            <div class="stat">External TCP<strong>{summary['external_tcp_connections']}</strong></div>
            <div class="stat">Response classes<strong>{summary['response_classes']}</strong></div>
        </section>

        <section class="content" id="boundary">
            <div class="section-head">
                <h2>One call, two data states</h2>
                <p>The tool is not starved of information. It completes its authorized computation first. Only the response crossing into the agent process is minimized.</p>
            </div>
            <div class="boundary">
                <article class="boundary-card">
                    <span class="label">Trusted execution zone</span>
                    <h3>Tool sees complete data</h3>
                    <ul><li>All authorized source rows</li><li>Observed identifiers and values</li><li>Full filtering and calculation context</li><li>Original successful ToolResult</li></ul>
                </article>
                <div class="gate">FASTMCP<br>RESULT<br>MIDDLEWARE</div>
                <article class="boundary-card">
                    <span class="label">Agent and model boundary</span>
                    <h3>LLM sees a safe sample</h3>
                    <ul><li>Column names and inferred types</li><li>Fixed synthetic example values</li><li>Explicit privacy policy metadata</li><li>No source rows or selected canaries</li></ul>
                </article>
            </div>
        </section>

        <section class="content" id="proof">
            <div class="section-head">
                <h2>Captured proof</h2>
                <p>Five deliberately sensitive response classes crossed a real gateway and upstream process tree over stdio. Every selected fixture canary was checked after middleware replacement.</p>
            </div>
            <div class="proof-grid">
                <aside class="process">
                    <h3>Observed process tree</h3>
                    <p>The client communicates with the gateway over <code>stdio</code>. The gateway launches the sensitive upstream fixture as a descendant process.</p>
                    <span class="pid">gateway: {gateway_pid}<br>children: {html.escape(descendant_pids)}</span>
                    <p><code>Get-NetTCPConnection</code> found {summary['loopback_tcp_connections']} local runtime entries and <strong>{summary['external_tcp_connections']} external connections</strong>. No model request or API key was used.</p>
                </aside>
                <div class="proof">
                    <table><thead><tr><th>Tool</th><th>Safe class</th><th>Response</th><th>Leaks</th></tr></thead><tbody>{proof_rows}</tbody></table>
                </div>
            </div>
        </section>

        <section class="content" id="artifacts">
            <div class="section-head"><h2>Audit artifacts</h2><p>Open the source evidence directly. The screenshot is presentation evidence; JSON and network logs are the reviewable record.</p></div>
            <div class="artifacts">
                <a class="artifact" href="gateway-evidence.json"><span>JSON</span><h3>Machine evidence</h3><p>Per-tool proof, process IDs, connection records, and summary.</p></a>
                <a class="artifact" href="gateway-network.log"><span>LOG</span><h3>Network capture</h3><p>Windows process and socket classification from the same run.</p></a>
                <a class="artifact" href="privacy-evidence.png"><span>PNG</span><h3>Report screenshot</h3><p>Confluence-ready visual evidence captured from this page.</p></a>
                <a class="artifact" href="../confluence-implementation-guide.md"><span>MD</span><h3>Implementation guide</h3><p>Library usage and the exact standalone FastMCP middleware pattern.</p></a>
            </div>
        </section>

        <section class="content" id="run">
            <div class="section-head"><h2>Demo in one click</h2><p>No model credential is needed. The launcher creates or reuses the local environment, installs the package, runs proof tests, regenerates evidence, and opens this page.</p></div>
            <div class="runbook">
                <article class="run-step"><span class="step-number">01</span><div><h3>Windows Explorer</h3><p>Double-click the root launcher.</p><div class="command"><span>RUN_DEMO.cmd</span><button type="button" data-copy="RUN_DEMO.cmd">Copy</button></div></div></article>
                <article class="run-step"><span class="step-number">02</span><div><h3>PowerShell or terminal</h3><p>Run the same launcher from the repository root.</p><div class="command"><span>.\\RUN_DEMO.cmd</span><button type="button" data-copy=".\\RUN_DEMO.cmd">Copy</button></div></div></article>
            </div>
        </section>

        <footer><span>Generated by <code>scripts/capture-privacy-evidence.py</code><br>Capture: {captured_at}</span><span>Schema-only claim applies to tested response paths.<br>Approved passthrough intentionally discloses complete successful results.</span></footer>
    </div>
    <div class="toast" role="status" aria-live="polite">Copied to clipboard</div>
    <script>
        const toast = document.querySelector('.toast');
        document.querySelectorAll('[data-copy]').forEach((button) => {{
            button.addEventListener('click', async () => {{
                const value = button.getAttribute('data-copy');
                try {{
                    await navigator.clipboard.writeText(value);
                }} catch {{
                    const area = document.createElement('textarea');
                    area.value = value;
                    document.body.appendChild(area);
                    area.select();
                    document.execCommand('copy');
                    area.remove();
                }}
                toast.classList.add('show');
                window.setTimeout(() => toast.classList.remove('show'), 1500);
            }});
        }});
    </script>
</body></html>"""


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
                "generated_at_utc": datetime.now(UTC).isoformat(timespec="seconds"),
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