# Privacy-Preserving MCP Analytics

## Goal

The language model may reason about statistics derived from MCP-managed data, but it
must not receive the underlying rows. This project enforces that rule at the MCP server
boundary rather than relying only on a prompt.

## Architecture

```mermaid
flowchart LR
    U[User question] --> L[Deep Agent and LLM]
    L -->|operation, grouping, filter| M[MCP tool]
    M --> D[(Raw rows inside MCP process)]
    D --> A[Local aggregate engine]
    A --> P[Privacy policy]
    P -->|schema, synthetic example, aggregates| L
    P -. blocks .-> X[Raw rows and identifiers]
```

The raw dataset is generated and analyzed in `server.py`. It exists only in the MCP
server process. The tool response is constructed separately and contains no `rows`
field or source identifiers.

The MCP server uses stdio, not HTTP. The separate Deep Agent process later sends the
user question and the approved aggregate-only tool result to the configured model over
HTTPS. Therefore, the precise guarantee is that **raw rows do not reach the agent or
LLM**; approved aggregates and metadata do reach the LLM so it can answer the question.

## Transport evidence

![Sanitized MCP evidence showing stdio transport and zero server TCP sockets](assets/privacy-evidence.png)

Run the evidence capture directly:

```powershell
.venv\Scripts\python.exe scripts\capture-privacy-evidence.py
```

The script opens a real MCP JSON-RPC session over the child process's stdin/stdout,
calls `get_products`, and inspects the MCP server PID with `Get-NetTCPConnection` on
Windows. It verifies the observed transport topology; the recursive payload assertions
in `smoke.py` separately enforce that the serialized response has no `rows` key and
contains the explicit privacy metadata.

The zero-socket observation is scoped to the MCP server process during that call. It
does not claim that the Deep Agent makes no network request: the agent uses HTTPS to
call the selected language-model provider after receiving the safe tool response.

## What the LLM receives

Each of the 34 tools returns only:

- `privacy`: an explicit statement that raw rows were not shared.
- `schema`: column names, valid categories/statuses, and the numeric metric.
- `example_row`: one hard-coded synthetic record using `EXAMPLE-0000` and
  `YYYY-MM-DD`; it is never copied from the dataset.
- `query`: the operation actually executed.
- `result`: a count or aggregate computed inside the MCP process.

The synthetic example teaches the model the shape and meaning of the data without
revealing a real row.

## Supported questions

All 34 domain tools support these operations:

| Operation | Answer produced |
| --- | --- |
| `overview` | Count, sum, average, minimum, maximum, category counts, status counts |
| `count` | Number of matching records |
| `sum` | Sum of the domain's numeric metric |
| `average` | Average numeric metric |
| `minimum` | Minimum numeric metric |
| `maximum` | Maximum numeric metric |
| `group_count` | Counts grouped by category, status, or date |
| `group_sum` | Sums grouped by category, status, or date |
| `group_average` | Averages grouped by category, status, or date |

Optional exact-match filtering is available for `category`, `status`, and `date`.
The model can therefore answer questions such as:

- "How many products are backordered?"
- "What is average product price by category?"
- "Which sales region has the highest average revenue?"
- "Compare active and cancelled subscription counts."
- "Give an overview of support tickets."

It intentionally cannot answer row-level questions such as "What is the name of the
most expensive customer?" because answering would disclose a source record.

## Small-cohort protection

Removing rows alone is insufficient. A filter matching one person followed by an
average query could reveal that person's value. The server therefore suppresses
numeric results when fewer than five rows match. Counts remain available, but sums,
averages, minima, maxima, and overviews return a suppression response.

This is a demonstration privacy control, not a full differential-privacy system.
Repeated and overlapping aggregate queries can still enable inference attacks in a
real dataset. Production systems should add authorization, query auditing, rate
limits, contribution bounds, and differential privacy where required.

## Why an interceptor is not enough

An MCP client interceptor could redact a result after receiving it, but then raw data
would already have crossed into the agent process. Here, aggregation happens inside
the MCP server and the server never serializes raw rows into the protocol response.
The system prompt is defense in depth; the server response contract is the primary
control.

## OpenAI-compatible model configuration

Keep credentials in `.env`, which is excluded by `.gitignore`. For an
OpenAI-compatible provider:

```dotenv
MODEL=openai:your-model-name
OPENAI_API_KEY=replace-with-a-new-key
OPENAI_BASE_URL=https://provider.example/v1
```

Do not commit `.env`. If a key has been pasted into chat, logs, an issue, or source
control, revoke it and create a new one before use.

For the demonstrated OpenAI-compatible endpoint, configure it without putting the key
on the command line:

```powershell
.\scripts\configure-provider.ps1 -BaseUrl "https://jianzhile.vip/v1"
```

## Verification

Run:

```powershell
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe -m deepagents_mcp_demo.smoke
```

The tests compare source rows against the public analysis response, assert that no
source ID or source name is present, verify deterministic grouped answers, and check
small-cohort suppression. The smoke test exercises the same contract across a real
stdio MCP session and fails if a `rows` field reaches the client.