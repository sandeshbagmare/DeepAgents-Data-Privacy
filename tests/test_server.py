import pytest

from deepagents_mcp_demo.server import TABLE_SPECS, analyze_table, build_table
from deepagents_mcp_demo.smoke import assert_private_payload, parse_tool_payload


def test_server_defines_exactly_34_unique_tools() -> None:
    names = [spec.tool_name for spec in TABLE_SPECS]
    assert len(names) == 34
    assert len(set(names)) == 34


def test_table_data_is_deterministic_and_tabular() -> None:
    first = build_table(TABLE_SPECS[0], limit=3, seed=7)
    second = build_table(TABLE_SPECS[0], limit=3, seed=7)

    assert first == second
    assert first["row_count"] == 3
    assert first["columns"] == list(first["rows"][0])


@pytest.mark.parametrize("limit", [0, 101])
def test_table_limit_is_validated(limit: int) -> None:
    with pytest.raises(ValueError, match="between 1 and 100"):
        build_table(TABLE_SPECS[0], limit=limit)


def test_analysis_does_not_expose_raw_rows() -> None:
    source = build_table(TABLE_SPECS[3], limit=100, seed=7)
    response = analyze_table(TABLE_SPECS[3], seed=7)

    assert "rows" not in response
    assert response["privacy"]["raw_rows_shared"] is False
    assert response["privacy"]["example_is_synthetic"] is True
    assert response["example_row"]["id"] == "EXAMPLE-0000"
    assert response["example_row"] not in source["rows"]
    assert all(row["id"] not in repr(response) for row in source["rows"])
    assert all(row["name"] not in repr(response) for row in source["rows"])


def test_grouped_analysis_answers_questions_without_rows() -> None:
    response = analyze_table(
        TABLE_SPECS[3], operation="group_average", group_by="category", seed=7
    )

    assert response["result"] == [
        {"category": "Hardware", "average": 2346.87},
        {"category": "Service", "average": 2448.82},
        {"category": "Software", "average": 2584.67},
    ]


def test_small_cohort_values_are_suppressed() -> None:
    response = analyze_table(
        TABLE_SPECS[3],
        operation="average",
        filter_field="date",
        filter_value="2026-01-01",
    )

    assert response["result"]["suppressed"] is True


def test_small_group_values_are_suppressed() -> None:
    response = analyze_table(
        TABLE_SPECS[3], operation="group_average", group_by="date"
    )

    assert any(group.get("suppressed") is True for group in response["result"])
    assert all(
        group["average"] is None
        for group in response["result"]
        if group.get("suppressed") is True
    )


def test_filter_requires_a_value() -> None:
    with pytest.raises(ValueError, match="filter_value"):
        analyze_table(TABLE_SPECS[3], filter_field="status")


def test_mcp_content_parser_checks_actual_payload() -> None:
    safe_result = [
        {
            "type": "text",
            "text": '{"privacy":{"raw_rows_shared":false},"example_row":{"id":"EXAMPLE-0000"}}',
        }
    ]
    assert_private_payload(parse_tool_payload(safe_result))

    unsafe_result = [
        {
            "type": "text",
            "text": '{"privacy":{"raw_rows_shared":false},"result":{"rows":[{"id":"REAL-1"}]}}',
        }
    ]
    with pytest.raises(RuntimeError, match="raw MCP rows"):
        assert_private_payload(parse_tool_payload(unsafe_result))
