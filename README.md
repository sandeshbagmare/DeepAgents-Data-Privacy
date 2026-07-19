# Deep Agents MCP Privacy

`deepagents-mcp-privacy` is a fail-closed Python gateway for putting MCP tools behind
a privacy boundary before connecting them to Deep Agents. It preserves tool names,
descriptions, and input schemas, but constructs new responses containing only data
shape, field names, and synthetic examples. Raw tool responses remain in the gateway
process and do not enter the Deep Agent process.

The default policy exposes no observed values, row counts, category labels, or
aggregates. Tables, structured objects, infrastructure responses, and JSON encoded as
text become safe structural descriptions. Unstructured text and unsupported content
are withheld because arbitrary prose cannot be generically de-identified safely.

The direct Python API also normalizes mappings, lists, tuples, named tuples,
dataclasses, Pydantic models, sets, frozen sets, dates/times, decimals, UUIDs, paths,
enums, and binary values. Recursive references and nesting deeper than 32 levels are
replaced with withheld markers. Unknown objects remain opaque, and containers that
cannot be traversed safely produce a generic withheld response.

## Install and plug in

Python 3.11 or newer is required.

```powershell
python -m pip install deepagents-mcp-privacy
```

Wrap the same connection mapping you would give to `MultiServerMCPClient`:

```python
from deepagents import create_deep_agent
from deepagents_mcp_privacy import create_private_mcp_client

connections = {
  "internal": {
    "transport": "stdio",
    "command": "python",
    "args": ["-m", "your_mcp_server"],
  }
}

client = create_private_mcp_client(connections)
tools = await client.get_tools()
agent = create_deep_agent(model=model, tools=tools)
```

The process topology is:

```mermaid
flowchart LR
  A[Deep Agent] <-->|safe MCP response| G[Privacy gateway process]
  G <-->|raw MCP response| U[Upstream MCP server]
  G --> S[Schema and synthetic examples]
  G -. blocks .-> R[Observed values and rows]
```

For in-process FastMCP composition, use `create_private_proxy(upstream, policy=...)`.
Use `sanitize_value(value)` when integrating the policy engine into another boundary.

## Disclosure policy

| Input | Default response |
| --- | --- |
| Table or list of records | Column names, types, synthetic row |
| Structured object | Nested field names, types, synthetic scalar examples |
| Infrastructure/status JSON | Shape only; hostnames, IPs, metrics, and states replaced |
| JSON string | Parsed and handled as structured data |
| Plain text | Withheld |
| Upstream error | Generic error; upstream message withheld |
| Images, audio, resources, mixed blocks | Withheld |

MCP wire values are JSON-compatible by protocol. The additional Python datatype
support applies when `sanitize_value()` or `create_private_proxy()` receives richer
in-process return values before FastMCP serialization.

Mapping keys that resemble emails, IP addresses, UUIDs, URLs, long tokens, or
free-form values are replaced with `SYNTHETIC_FIELD_n`. Stable field names are exposed
because an LLM needs structure to call and interpret tools. If field names themselves
are sensitive in your domain, do not expose that MCP server without a domain-specific
schema allowlist.

Counts and numeric aggregates are available only as explicit policy opt-ins:

```python
client = create_private_mcp_client(
  connections,
  minimum_cohort_size=5,
  expose_counts=True,
  expose_aggregates=True,
)
```

Category values are replaced by synthetic group labels. Numeric and grouped results
are suppressed below the cohort threshold. Aggregate mode still reveals information
derived from real data and is not equivalent to the schema-only default.

### Trusted raw passthrough

The gateway can forward the complete successful MCP result for explicitly trusted
tools. Every unlisted tool remains schema-only:

```python
client = create_private_mcp_client(
  connections,
  passthrough_tools=("get_public_catalog", "get_documentation"),
)
```

To forward successful results from every tool, use the wildcard explicitly:

```python
client = create_private_mcp_client(
  connections,
  passthrough_tools=("*",),
)
```

Passthrough returns the upstream `ToolResult` without sanitizing its content,
structured content, or metadata. It therefore allows raw values to enter the agent
process and potentially the model request. Upstream errors remain generic and do not
pass through. Treat the allowlist as a privileged disclosure policy: use stable tool
names, read-only sources, least privilege, data-owner approval, and tests that prove
neighboring tools remain private. An empty allowlist is the default.

For custom plain-text handling, use an in-process `PrivacyPolicy.text_sanitizers`
callback that returns a structured intermediate object. The normal sanitizer runs
again on that object, so callback output values are still replaced before disclosure.

## 34-tool demo

The repository also includes a complete private analytics demonstration. Its local
FastMCP server owns and analyzes generated rows and exposes exactly **34 deterministic,
read-only table tools** over stdio. This server is already aggregate-safe; the demo
Deep Agent additionally routes it through the generic gateway.

The server exposes exactly **34 deterministic, read-only table tools** through MCP over
stdio. Every tool supports counts, numeric aggregates, grouping, and exact-match
filters while enforcing a minimum numeric cohort size of five.

> [!IMPORTANT]
> The demo server is an **aggregate-only** design. The generic gateway defaults to the
> stricter schema-only policy. In both modes, tool metadata and synthetic structure
> reach the LLM; user questions also reach the selected model provider.

![Privacy evidence showing stdio transport, blocked canaries, and zero external TCP connections](docs/assets/privacy-evidence.png)

The screenshot is generated from a real MCP tool call. Reproduce the underlying check
with `python scripts/capture-privacy-evidence.py`; it requires no API key.

## Demo privacy boundary

```mermaid
flowchart LR
    U[User question] --> A[Deep Agent process]
    A -->|operation + filter + grouping| M[Local MCP server over stdio]
    M --> R[(Raw rows in MCP process memory)]
    R --> G[Filter and aggregate locally]
    G --> P{Privacy policy}
    P -->|safe cohort| S[Aggregate-only MCP response]
    P -->|cohort under 5| X[Suppressed numeric result]
    S --> A
    A -->|question + approved tool result over HTTPS| L[Configured LLM provider]
    R -. never serialized .-> A
    R -. never sent .-> L
```

There are two different transports:

1. **MCP transport:** The agent launches the MCP server as a child process and uses
   stdin/stdout. The server does not make a network call to return tool data.
2. **Model transport:** The agent calls the configured OpenAI-compatible provider over
   HTTPS. The model request can include the user question and the aggregate-only MCP
   result, but not the raw source rows.

The server boundary is the primary control. The system prompt is defense in depth and
guides the model to refuse row-level requests, but privacy does not depend on the model
obeying that prompt.

## What Crosses the Boundary

| Item | Agent/LLM receives it? | Notes |
| --- | --- | --- |
| Raw `rows` collection | No | Exists only inside the MCP server process |
| Real record ID or name | No | Never copied into a tool response |
| Schema and metric name | Yes | Needed to interpret aggregates |
| Allowed categories/statuses | Yes | Metadata, not observed row values |
| Synthetic example | Yes | Fixed `EXAMPLE-0000`; never sampled from raw rows |
| Count | Yes | Counts are intentionally permitted |
| Sum/average/minimum/maximum | Sometimes | Suppressed when the matching cohort has fewer than five rows |
| Grouped numeric result | Sometimes | Each group smaller than five is independently suppressed |
| User question | Yes | Sent to the selected model provider when the agent runs |

An actual safe MCP response has this shape:

```json
{
  "title": "Products",
  "privacy": {
    "raw_rows_shared": false,
    "processing_location": "MCP server",
    "example_is_synthetic": true,
    "minimum_cohort_size": 5
  },
  "schema": {
    "columns": ["id", "name", "category", "status", "price", "date"],
    "numeric_metric": "price"
  },
  "example_row": {
    "id": "EXAMPLE-0000",
    "name": "Example Product",
    "price": 123.45
  },
  "query": {
    "operation": "group_average",
    "group_by": "category",
    "seed": 7
  },
  "result": [
    {"category": "Hardware", "average": 2346.87},
    {"category": "Service", "average": 2448.82},
    {"category": "Software", "average": 2584.67}
  ]
}
```

Notice that `schema.columns` describes an `id` and `name` column, but the response does
not contain any real ID or name values. The example values are hard-coded synthetic
values used only to teach the model the record shape.

## Query Examples

All tools accept the same interface:

| Parameter | Values |
| --- | --- |
| `operation` | `overview`, `count`, `sum`, `average`, `minimum`, `maximum`, `group_count`, `group_sum`, `group_average` |
| `group_by` | `category`, `status`, `date` |
| `filter_field` | `category`, `status`, `date` |
| `filter_value` | Case-insensitive exact match |
| `seed` | Integer controlling deterministic demo generation |

Safe questions include:

```text
Compare average product price by category.
How many products are backordered?
Which sales region has the highest average revenue?
Compare active and cancelled subscription counts.
Give an overview of support tickets.
```

For example, "How many products are backordered?" becomes:

```json
{
  "operation": "count",
  "filter_field": "status",
  "filter_value": "Backorder"
}
```

A row-level request such as "Give me the real name and ID of the most expensive
customer" is refused. The agent can instead call `get_customers` with `maximum` and
report the highest `lifetime_value` without revealing which customer produced it.

If a numeric filter matches fewer than five rows, the response is:

```json
{
  "suppressed": true,
  "reason": "Fewer than 5 records match the query"
}
```

## The 34 Tools

`get_people`, `get_customers`, `get_employees`, `get_products`, `get_orders`,
`get_sales`, `get_inventory`, `get_shipments`, `get_suppliers`, `get_weather`,
`get_transactions`, `get_budgets`, `get_invoices`, `get_support_tickets`,
`get_projects`, `get_tasks`, `get_events`, `get_books`, `get_movies`, `get_teams`,
`get_matches`, `get_flights`, `get_hotels`, `get_devices`, `get_sensors`,
`get_web_metrics`, `get_campaigns`, `get_leads`, `get_subscriptions`, `get_payments`,
`get_restaurants`, `get_recipes`, `get_courses`, and `get_students`.

## Development setup

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
```

Verify the privacy contract without any model credential:

```powershell
table-mcp-smoke
python scripts/capture-privacy-evidence.py
pytest -q
```

The smoke test starts a real stdio MCP session, confirms that exactly 34 tools are
advertised, parses the returned JSON object, recursively rejects any `rows` key, and
requires the explicit synthetic-example and no-raw-rows guarantees.

## Model Provider

Use the secure setup helper. It prompts for the key without echoing it, discovers model
IDs, and writes only to the ignored local `.env` file:

```powershell
.\scripts\configure-provider.ps1 -BaseUrl "https://jianzhile.vip/v1"
```

Then run:

```powershell
table-deep-agent "Compare average product price by category."
```

The provider must support the OpenAI Chat Completions API. This project explicitly
uses Chat Completions rather than the Responses API for compatibility. Never put an
API key in a command argument, source file, screenshot, issue, or chat. A key pasted
into any of those locations must be revoked and replaced before use.

## Reproducing the Evidence

The evidence utility launches the server using the current Python interpreter, sends
raw MCP JSON-RPC messages over stdin, calls `get_products`, parses the returned content,
and prints only a sanitized summary. On Windows it also queries
`Get-NetTCPConnection -OwningProcess <pid>` while the MCP server is alive.

Expected evidence:

```json
{
  "mcp_transport": "stdio",
  "server_tcp_connections": 0,
  "response_top_level_keys": [
    "title", "privacy", "schema", "example_row", "query", "result"
  ],
  "raw_rows_shared": false,
  "example_is_synthetic": true
}
```

Zero TCP connections apply to the **MCP server process during this local tool call**.
The separate agent process makes an HTTPS connection when it sends the user question
and approved aggregate result to the configured model provider.

## QA Coverage

The test suite covers deterministic generation, exactly 34 unique tools, invalid
limits, absence of raw IDs and names, grouping, filtering, minimum cohort suppression,
recursive MCP payload inspection, and the row-level refusal prompt. The full QA pass
also exercised 578 combinations across all tools, operations, groupings, and filters.

```powershell
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe -m compileall -q src tests scripts
.venv\Scripts\python.exe -m pip check
```

## Limitations

This library controls tool **results**, not tool arguments, prompts, model retention,
MCP server behavior, or gateway host security. Tool arguments chosen by the agent are
visible to the upstream MCP server. Tool metadata and field names remain visible to
the model. A compromised gateway process can observe upstream results in memory.

Schema-only mode minimizes disclosure but does not prove formal anonymity. Aggregate
mode can support inference through repeated or overlapping queries. Production systems
should add authentication, authorization, schema allowlists, query auditing, rate
limits, contribution bounds, privacy budgets or differential privacy, provider
retention controls, and an independent security review.

Raw passthrough intentionally removes the result privacy guarantee for selected tools.
Tool authorization and data classification must be enforced upstream; the gateway does
not inspect or partially redact an approved passthrough result.

See [docs/privacy-architecture.md](docs/privacy-architecture.md) for the detailed threat
model and implementation rationale. VS Code can launch the local server using
[.vscode/mcp.json](.vscode/mcp.json).

For an enterprise adoption proposal, reproducible gateway statistics, process/network
logs, and screenshot evidence, see
[docs/confluence-proposal.md](docs/confluence-proposal.md).
