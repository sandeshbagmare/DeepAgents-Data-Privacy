from deepagents_mcp_demo.agent import PRIVACY_SYSTEM_PROMPT


def test_privacy_prompt_requires_safe_row_level_refusal() -> None:
    assert "individual raw record" in PRIVACY_SYSTEM_PROMPT
    assert "privacy boundary does not expose it" in PRIVACY_SYSTEM_PROMPT
    assert "numeric_metric" in PRIVACY_SYSTEM_PROMPT
    assert "Never claim the example is a real record" in PRIVACY_SYSTEM_PROMPT