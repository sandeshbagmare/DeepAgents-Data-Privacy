# Deep Agents MCP Demo

- Use Python 3.11 or newer and preserve the `src` package layout.
- Keep the MCP transport on stdio for local development.
- Keep `TABLE_SPECS` at exactly 34 unique, read-only table tools.
- Keep raw generated rows inside the MCP server process; never return them from tools.
- Return only schema, one synthetic example, query metadata, and safe aggregates.
- Suppress numeric aggregates for cohorts and groups smaller than five records.
- Keep generated demo data deterministic for a given tool and seed.
- Follow the official MCP Python SDK documentation: https://github.com/modelcontextprotocol/python-sdk
- Follow the MCP protocol documentation: https://modelcontextprotocol.io/docs
- Follow Deep Agents documentation: https://docs.langchain.com/oss/python/deepagents/overview
