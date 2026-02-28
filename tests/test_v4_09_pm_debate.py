from openclaw.pm_debate import build_debate_prompt


def test_pm_debate_prompt_contains_required_fields():
    prompt = build_debate_prompt({"symbol": "2330", "facts": ["A", "B"]})

    # Roles
    assert "bull_case" in prompt
    assert "bear_case" in prompt
    assert "neutral_case" in prompt

    # Required outputs
    assert "consensus_points" in prompt
    assert "divergence_points" in prompt
    assert "recommended_action" in prompt
    assert "confidence" in prompt

    # Still includes context payload
    assert "context=" in prompt
