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


def test_pm_debate_prompt_empty_positions_injects_constraint():
    """空倉時 prompt 應注入「勿捏造歷史」約束。"""
    prompt = build_debate_prompt({"open_positions": [], "recent_trades": []})
    assert "空倉" in prompt or "empty" in prompt.lower() or "捏造" in prompt
    assert "open_positions" in str({"open_positions": []})  # sanity
    # 具體驗證 portfolio_constraint 文字
    assert "不得" in prompt or "請勿" in prompt


def test_pm_debate_prompt_with_positions_no_empty_constraint():
    """有持倉時不應出現空倉約束文字。"""
    ctx = {
        "open_positions": [{"symbol": "2330", "quantity": 1000, "avg_price": 100.0}],
        "recent_trades": [],
    }
    prompt = build_debate_prompt(ctx)
    # 不應有空倉警告
    assert "從未建立" not in prompt
    assert "捏造" not in prompt
