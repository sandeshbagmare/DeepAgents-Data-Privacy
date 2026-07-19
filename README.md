# Deep Agents MCP Table Demo

A local MCP server exposing exactly **34 read-only analytics tools**. Raw rows stay in
the MCP server process; the Deep Agent receives only schema, one synthetic example,
and server-computed aggregates through `langchain-mcp-adapters`.

See [docs/privacy-architecture.md](docs/privacy-architecture.md) for the complete data
flow, supported questions, threat model, limitations, and verification procedure.

## Setup

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
```

## Verify MCP without an API key

```powershell
table-mcp-smoke
```

This launches the server over stdio, verifies that it advertises 34 tools, calls
`get_products`, and confirms that only aggregate data reaches the client.

## Run the Deep Agent

Copy `.env.example` to `.env`, choose a LangChain model identifier, and provide the
matching provider API key. Then run:

```powershell
table-deep-agent "Compare average product price by category and summarize inventory."
```

The default question works with just `table-deep-agent`. To use another provider,
install its LangChain integration package and change `MODEL`.

## Private analytics format

Every tool accepts an aggregate `operation`, optional grouping/filter arguments, and a
`seed`. Source rows are never part of the MCP response:

```json
{
  "title": "Products",
  "privacy": {"raw_rows_shared": false, "example_is_synthetic": true},
  "schema": {"numeric_metric": "price"},
  "example_row": {"id": "EXAMPLE-0000", "name": "Example Product"},
  "query": {"operation": "group_average", "group_by": "category"},
  "result": [{"category": "Hardware", "average": 2346.87}]
}
```

The 34 domains include people, customers, employees, products, orders, sales,
inventory, shipping, finance, support, projects, media, sports, travel, devices,
analytics, education, restaurants, and more.

Supported operations are `overview`, `count`, `sum`, `average`, `minimum`, `maximum`,
`group_count`, `group_sum`, and `group_average`. Numeric results for cohorts smaller
than five records are suppressed.

## VS Code MCP

After creating `.venv` and installing the project, [.vscode/mcp.json](.vscode/mcp.json)
lets VS Code start and debug the `table-data-demo` MCP server. Open the MCP Servers
view or run the MCP server command from the Command Palette.

## Tests

```powershell
pytest
```