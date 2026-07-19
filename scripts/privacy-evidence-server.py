from __future__ import annotations

from fastmcp import FastMCP

mcp = FastMCP("Privacy Evidence Source")


@mcp.tool
def customer_rows() -> dict[str, object]:
    """Return deliberately sensitive customer rows for gateway verification."""
    return {
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
    }


@mcp.tool
def infrastructure_status() -> dict[str, object]:
    """Return private infrastructure state for gateway verification."""
    return {
        "service": "payments-production",
        "healthy": False,
        "latency_ms": 83.7,
        "nodes": [
            {"hostname": "prod-pay-01", "ip_address": "10.42.0.11", "load": 71.2},
            {"hostname": "prod-pay-02", "ip_address": "10.42.0.12", "load": 68.4},
        ],
    }


@mcp.tool
def nested_metrics() -> dict[str, object]:
    """Return nested private metrics and value-like mapping keys."""
    return {
        "tenant_metrics": {
            "alice@private.example": {"requests": 912, "error_rate": 0.17},
            "10.42.0.15": {"requests": 441, "error_rate": 0.08},
        }
    }


@mcp.tool
def private_note() -> str:
    """Return unstructured prose that must be withheld."""
    return "Private Person 7 owes 4821 dollars on account SECRET-77"


@mcp.tool
def private_failure() -> str:
    """Raise an error containing private details."""
    raise RuntimeError("Database password SECRET-PASSWORD failed on prod-db-01")


if __name__ == "__main__":
    mcp.run(transport="stdio", show_banner=False)