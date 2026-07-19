from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Callable, Literal

from fastmcp import FastMCP


@dataclass(frozen=True)
class TableSpec:
    tool_name: str
    title: str
    item_label: str
    categories: tuple[str, ...]
    statuses: tuple[str, ...]
    value_label: str


TABLE_SPECS = (
    TableSpec("get_people", "People", "Person", ("Engineering", "Design", "Sales"), ("Active", "Away", "Offline"), "age"),
    TableSpec("get_customers", "Customers", "Customer", ("Retail", "Business", "Enterprise"), ("New", "Active", "At risk"), "lifetime_value"),
    TableSpec("get_employees", "Employees", "Employee", ("Product", "Operations", "Finance"), ("Onsite", "Remote", "Leave"), "salary"),
    TableSpec("get_products", "Products", "Product", ("Hardware", "Software", "Service"), ("In stock", "Low stock", "Backorder"), "price"),
    TableSpec("get_orders", "Orders", "Order", ("Online", "Store", "Partner"), ("Pending", "Shipped", "Delivered"), "total"),
    TableSpec("get_sales", "Sales", "Sale", ("North", "South", "West"), ("Open", "Won", "Lost"), "revenue"),
    TableSpec("get_inventory", "Inventory", "SKU", ("Warehouse A", "Warehouse B", "Warehouse C"), ("Healthy", "Low", "Out"), "quantity"),
    TableSpec("get_shipments", "Shipments", "Shipment", ("Air", "Ground", "Sea"), ("Packed", "In transit", "Arrived"), "weight_kg"),
    TableSpec("get_suppliers", "Suppliers", "Supplier", ("Local", "Regional", "Global"), ("Approved", "Review", "Paused"), "rating"),
    TableSpec("get_weather", "Weather", "City", ("Coastal", "Inland", "Mountain"), ("Sunny", "Cloudy", "Rain"), "temperature_c"),
    TableSpec("get_transactions", "Transactions", "Transaction", ("Card", "Bank", "Wallet"), ("Pending", "Settled", "Declined"), "amount"),
    TableSpec("get_budgets", "Budgets", "Budget", ("Marketing", "Engineering", "Operations"), ("On track", "Watch", "Exceeded"), "allocated"),
    TableSpec("get_invoices", "Invoices", "Invoice", ("Monthly", "Quarterly", "Annual"), ("Draft", "Sent", "Paid"), "balance"),
    TableSpec("get_support_tickets", "Support Tickets", "Ticket", ("Billing", "Technical", "Account"), ("Open", "Waiting", "Resolved"), "priority_score"),
    TableSpec("get_projects", "Projects", "Project", ("Internal", "Client", "Research"), ("Planned", "Active", "Complete"), "progress_percent"),
    TableSpec("get_tasks", "Tasks", "Task", ("Feature", "Bug", "Documentation"), ("Todo", "Doing", "Done"), "estimate_hours"),
    TableSpec("get_events", "Events", "Event", ("Conference", "Workshop", "Meetup"), ("Scheduled", "Live", "Finished"), "attendees"),
    TableSpec("get_books", "Books", "Book", ("Fiction", "Science", "History"), ("Available", "Reserved", "Checked out"), "pages"),
    TableSpec("get_movies", "Movies", "Movie", ("Drama", "Comedy", "Documentary"), ("Now showing", "Upcoming", "Archived"), "runtime_minutes"),
    TableSpec("get_teams", "Teams", "Team", ("Premier", "Division 1", "Division 2"), ("Training", "Playing", "Resting"), "points"),
    TableSpec("get_matches", "Matches", "Match", ("League", "Cup", "Friendly"), ("Scheduled", "Live", "Final"), "attendance"),
    TableSpec("get_flights", "Flights", "Flight", ("Domestic", "Regional", "International"), ("On time", "Delayed", "Boarding"), "fare"),
    TableSpec("get_hotels", "Hotels", "Hotel", ("Business", "Resort", "Boutique"), ("Available", "Limited", "Full"), "nightly_rate"),
    TableSpec("get_devices", "Devices", "Device", ("Laptop", "Phone", "Tablet"), ("Online", "Offline", "Maintenance"), "battery_percent"),
    TableSpec("get_sensors", "Sensors", "Sensor", ("Temperature", "Pressure", "Humidity"), ("Normal", "Warning", "Critical"), "reading"),
    TableSpec("get_web_metrics", "Web Metrics", "Page", ("Landing", "Product", "Checkout"), ("Growing", "Stable", "Falling"), "views"),
    TableSpec("get_campaigns", "Campaigns", "Campaign", ("Email", "Social", "Search"), ("Draft", "Running", "Complete"), "conversions"),
    TableSpec("get_leads", "Leads", "Lead", ("Inbound", "Outbound", "Referral"), ("New", "Qualified", "Closed"), "score"),
    TableSpec("get_subscriptions", "Subscriptions", "Subscription", ("Basic", "Pro", "Enterprise"), ("Trial", "Active", "Cancelled"), "monthly_value"),
    TableSpec("get_payments", "Payments", "Payment", ("Card", "Transfer", "Cash"), ("Created", "Processed", "Refunded"), "amount"),
    TableSpec("get_restaurants", "Restaurants", "Restaurant", ("Cafe", "Casual", "Fine dining"), ("Open", "Busy", "Closed"), "average_bill"),
    TableSpec("get_recipes", "Recipes", "Recipe", ("Breakfast", "Lunch", "Dinner"), ("Easy", "Medium", "Advanced"), "prep_minutes"),
    TableSpec("get_courses", "Courses", "Course", ("Technology", "Business", "Arts"), ("Open", "In progress", "Complete"), "duration_hours"),
    TableSpec("get_students", "Students", "Student", ("Freshman", "Sophomore", "Senior"), ("Enrolled", "Leave", "Graduated"), "grade_percent"),
)

if len(TABLE_SPECS) != 34:
    raise RuntimeError("The demo server must expose exactly 34 table tools")


def build_table(spec: TableSpec, limit: int = 10, seed: int = 42) -> dict[str, Any]:
    """Build deterministic demo rows for a table specification."""
    if not 1 <= limit <= 100:
        raise ValueError("limit must be between 1 and 100")

    generator = random.Random(f"{spec.tool_name}:{seed}")
    first_day = date(2026, 1, 1)
    rows = []
    for index in range(1, limit + 1):
        rows.append(
            {
                "id": f"{spec.tool_name.removeprefix('get_')[:3].upper()}-{index:04d}",
                "name": f"{spec.item_label} {generator.randint(100, 999)}",
                "category": generator.choice(spec.categories),
                "status": generator.choice(spec.statuses),
                spec.value_label: round(generator.uniform(10, 5000), 2),
                "date": (first_day + timedelta(days=generator.randint(0, 364))).isoformat(),
            }
        )

    return {
        "title": spec.title,
        "columns": list(rows[0]),
        "rows": rows,
        "row_count": len(rows),
        "seed": seed,
    }


Operation = Literal[
    "overview",
    "count",
    "sum",
    "average",
    "minimum",
    "maximum",
    "group_count",
    "group_sum",
    "group_average",
]
GroupField = Literal["category", "status", "date"]
FilterField = Literal["category", "status", "date"]
MIN_COHORT_SIZE = 5


def _synthetic_example(spec: TableSpec) -> dict[str, Any]:
    return {
        "id": "EXAMPLE-0000",
        "name": f"Example {spec.item_label}",
        "category": spec.categories[0],
        "status": spec.statuses[0],
        spec.value_label: 123.45,
        "date": "YYYY-MM-DD",
    }


def analyze_table(
    spec: TableSpec,
    operation: Operation = "overview",
    group_by: GroupField = "category",
    filter_field: FilterField | None = None,
    filter_value: str | None = None,
    seed: int = 42,
) -> dict[str, Any]:
    """Compute an aggregate inside the MCP process without returning source rows."""
    table = build_table(spec, limit=100, seed=seed)
    rows = table["rows"]
    if filter_field is not None:
        if filter_value is None:
            raise ValueError("filter_value is required when filter_field is set")
        rows = [row for row in rows if str(row[filter_field]).casefold() == filter_value.casefold()]

    values = [float(row[spec.value_label]) for row in rows]
    cohort_is_safe = len(rows) >= MIN_COHORT_SIZE
    if operation == "count":
        result: Any = {"count": len(rows)}
    elif not cohort_is_safe:
        result = {
            "suppressed": True,
            "reason": f"Fewer than {MIN_COHORT_SIZE} records match the query",
        }
    elif operation == "overview":
        result: Any = {
            "count": len(rows),
            f"{spec.value_label}_sum": round(sum(values), 2),
            f"{spec.value_label}_average": round(sum(values) / len(values), 2) if values else None,
            f"{spec.value_label}_minimum": min(values, default=None),
            f"{spec.value_label}_maximum": max(values, default=None),
            "category_counts": _group_values(rows, "category", None),
            "status_counts": _group_values(rows, "status", None),
        }
    elif operation in {"sum", "average", "minimum", "maximum"}:
        result = {spec.value_label: _aggregate_values(values, operation)}
    else:
        aggregate = operation.removeprefix("group_")
        result = _group_values(rows, group_by, spec.value_label if aggregate != "count" else None, aggregate)

    return {
        "title": spec.title,
        "privacy": {
            "raw_rows_shared": False,
            "processing_location": "MCP server",
            "example_is_synthetic": True,
            "minimum_cohort_size": MIN_COHORT_SIZE,
        },
        "schema": {
            "columns": table["columns"],
            "numeric_metric": spec.value_label,
            "allowed_categories": list(spec.categories),
            "allowed_statuses": list(spec.statuses),
        },
        "example_row": _synthetic_example(spec),
        "query": {
            "operation": operation,
            "group_by": group_by if operation.startswith("group_") else None,
            "filter_field": filter_field,
            "filter_value": filter_value,
            "seed": seed,
        },
        "result": result,
    }


def _aggregate_values(values: list[float], operation: str) -> float | None:
    if not values:
        return None
    if operation == "sum":
        return round(sum(values), 2)
    if operation == "average":
        return round(sum(values) / len(values), 2)
    if operation == "minimum":
        return min(values)
    return max(values)


def _group_values(
    rows: list[dict[str, Any]],
    group_by: str,
    metric: str | None,
    operation: str = "count",
) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        groups.setdefault(str(row[group_by]), []).append(row)

    result = []
    for group, group_rows in sorted(groups.items()):
        if operation == "count":
            value: float | int | None = len(group_rows)
        elif len(group_rows) < MIN_COHORT_SIZE:
            value = None
        else:
            values = [float(row[metric]) for row in group_rows] if metric else []
            value = _aggregate_values(values, operation)
        group_result = {group_by: group, operation: value}
        if operation != "count" and len(group_rows) < MIN_COHORT_SIZE:
            group_result["suppressed"] = True
        result.append(group_result)
    return result


def create_table_tool(spec: TableSpec) -> Callable[..., dict[str, Any]]:
    def table_tool(
        operation: Operation = "overview",
        group_by: GroupField = "category",
        filter_field: FilterField | None = None,
        filter_value: str | None = None,
        seed: int = 42,
    ) -> dict[str, Any]:
        return analyze_table(
            spec,
            operation=operation,
            group_by=group_by,
            filter_field=filter_field,
            filter_value=filter_value,
            seed=seed,
        )

    table_tool.__name__ = spec.tool_name
    table_tool.__doc__ = (
        f"Privately analyze {spec.title.lower()} inside the MCP server. Returns only "
        "aggregates, schema, and one synthetic example; raw rows never leave the server."
    )
    return table_tool


mcp = FastMCP("Table Data Demo")
for table_spec in TABLE_SPECS:
    mcp.tool(name=table_spec.tool_name)(create_table_tool(table_spec))


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()