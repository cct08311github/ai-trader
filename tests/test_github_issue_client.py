"""tests/test_github_issue_client.py — github_issue_client 單元測試 [Issue #196]"""
from __future__ import annotations

import json
import os
from io import BytesIO
from unittest.mock import MagicMock, patch

import pytest

from openclaw.github_issue_client import (
    _build_strategy_body,
    _fmt_pct,
    ensure_labels,
    open_bear_dissent_issue,
    open_strategy_proposal_issue,
)


# ── 輔助 ─────────────────────────────────────────────────────────────────────

def _make_response(body: dict, status: int = 200):
    """模擬 urllib 回應物件。"""
    raw = json.dumps(body).encode()
    resp = MagicMock()
    resp.read.return_value = raw
    resp.status = status
    resp.__enter__ = lambda s: s
    resp.__exit__ = MagicMock(return_value=False)
    return resp


def _mock_token(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "fake-token")
    monkeypatch.setenv("GITHUB_OWNER", "testowner")
    monkeypatch.setenv("GITHUB_REPO", "testrepo")
    import openclaw.github_issue_client as m
    # 讓 module-level 函數讀到最新環境變數
    monkeypatch.setattr(m, "_token", lambda: "fake-token")
    monkeypatch.setattr(m, "_owner", lambda: "testowner")
    monkeypatch.setattr(m, "_repo", lambda: "testrepo")


# ── _fmt_pct ─────────────────────────────────────────────────────────────────

class TestFmtPct:
    def test_positive(self):
        assert "+" in _fmt_pct(3.5)
        assert "3.5" in _fmt_pct(3.5)

    def test_negative(self):
        result = _fmt_pct(-2.1)
        assert "-" in result
        assert "2.1" in result

    def test_none(self):
        assert _fmt_pct(None) == "N/A"


# ── _build_strategy_body ──────────────────────────────────────────────────────

class TestBuildStrategyBody:
    def _make_ctx(self, stance="bull"):
        return {
            "bull": {"thesis": "看多因技術指標強勁", "confidence": 0.7},
            "bear": {"thesis": "外資持續賣超", "confidence": 0.5},
            "arbiter": {"summary": "偏多但注意風控", "stance": stance},
            "market_data": {"index": "10000"},
        }

    def test_contains_proposal_id(self):
        body = _build_strategy_body(
            {"target_rule": "trailing_pct", "proposed_value": "0.08",
             "supporting_evidence": "MA20 支撐", "confidence": 0.65},
            self._make_ctx(),
            proposal_id="abc-123",
        )
        assert "abc-123" in body

    def test_contains_stance(self):
        body = _build_strategy_body(
            {"target_rule": "r", "proposed_value": "v",
             "supporting_evidence": "e", "confidence": 0.6},
            self._make_ctx(stance="bear"),
            proposal_id="xyz",
        )
        assert "bear" in body

    def test_contains_bull_and_bear_thesis(self):
        ctx = self._make_ctx()
        body = _build_strategy_body(
            {"target_rule": "r", "proposed_value": "v",
             "supporting_evidence": "e", "confidence": 0.6},
            ctx,
            proposal_id=None,
        )
        assert "看多因技術指標強勁" in body
        assert "外資持續賣超" in body


# ── open_strategy_proposal_issue ─────────────────────────────────────────────

class TestOpenStrategyProposalIssue:
    _proposal = {
        "target_rule": "trailing_pct",
        "proposed_value": "0.08",
        "supporting_evidence": "MA20 黃金交叉",
        "confidence": 0.72,
    }
    _ctx = {
        "bull": {"thesis": "多方", "confidence": 0.7},
        "bear": {"thesis": "空方", "confidence": 0.5},
        "arbiter": {"summary": "偏多", "stance": "bull"},
        "market_data": "指數 10000",
    }

    def test_returns_none_without_token(self, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "")
        import openclaw.github_issue_client as m
        monkeypatch.setattr(m, "_token", lambda: "")
        result = open_strategy_proposal_issue(self._proposal, self._ctx)
        assert result is None

    def test_returns_url_on_success(self, monkeypatch):
        _mock_token(monkeypatch)
        mock_resp = _make_response({"html_url": "https://github.com/t/r/issues/1", "number": 1})
        with patch("urllib.request.urlopen", return_value=mock_resp):
            url = open_strategy_proposal_issue(self._proposal, self._ctx, proposal_id="p-1")
        assert url == "https://github.com/t/r/issues/1"

    def test_returns_none_on_network_error(self, monkeypatch):
        _mock_token(monkeypatch)
        with patch("urllib.request.urlopen", side_effect=Exception("connection refused")):
            result = open_strategy_proposal_issue(self._proposal, self._ctx)
        assert result is None

    def test_high_confidence_gets_p1_label(self, monkeypatch):
        _mock_token(monkeypatch)
        captured_body: list[dict] = []

        def fake_urlopen(req, timeout=None):
            captured_body.append(json.loads(req.data.decode()))
            return _make_response({"html_url": "https://github.com/t/r/issues/2", "number": 2})

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            open_strategy_proposal_issue(
                {**self._proposal, "confidence": 0.8},
                self._ctx,
            )

        assert "P1" in captured_body[0]["labels"]

    def test_low_confidence_gets_p3_label(self, monkeypatch):
        _mock_token(monkeypatch)
        captured_body: list[dict] = []

        def fake_urlopen(req, timeout=None):
            captured_body.append(json.loads(req.data.decode()))
            return _make_response({"html_url": "https://github.com/t/r/issues/3", "number": 3})

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            open_strategy_proposal_issue(
                {**self._proposal, "confidence": 0.3},
                self._ctx,
            )

        assert "P3" in captured_body[0]["labels"]

    def test_bear_stance_adds_discussion_label(self, monkeypatch):
        _mock_token(monkeypatch)
        captured_body: list[dict] = []

        def fake_urlopen(req, timeout=None):
            captured_body.append(json.loads(req.data.decode()))
            return _make_response({"html_url": "https://github.com/t/r/issues/4", "number": 4})

        ctx_bear = {**self._ctx, "arbiter": {"summary": "偏空", "stance": "bear"}}
        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            open_strategy_proposal_issue(self._proposal, ctx_bear)

        assert "discussion" in captured_body[0]["labels"]


# ── open_bear_dissent_issue ───────────────────────────────────────────────────

class TestOpenBearDissentIssue:
    def test_returns_none_without_token(self, monkeypatch):
        import openclaw.github_issue_client as m
        monkeypatch.setattr(m, "_token", lambda: "")
        result = open_bear_dissent_issue("bear thesis", {}, 0.75)
        assert result is None

    def test_returns_url_on_success(self, monkeypatch):
        _mock_token(monkeypatch)
        mock_resp = _make_response({"html_url": "https://github.com/t/r/issues/5", "number": 5})
        with patch("urllib.request.urlopen", return_value=mock_resp):
            url = open_bear_dissent_issue("外資賣超嚴重", {"vix": 28}, 0.78, "p-99")
        assert url == "https://github.com/t/r/issues/5"

    def test_title_contains_confidence(self, monkeypatch):
        _mock_token(monkeypatch)
        captured: list[dict] = []

        def fake_urlopen(req, timeout=None):
            captured.append(json.loads(req.data.decode()))
            return _make_response({"html_url": "https://github.com/t/r/issues/6", "number": 6})

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            open_bear_dissent_issue("風險高", {}, 0.82)

        assert "82%" in captured[0]["title"]


# ── ensure_labels ─────────────────────────────────────────────────────────────

class TestEnsureLabels:
    def test_skips_existing_labels(self, monkeypatch):
        _mock_token(monkeypatch)
        existing = [{"name": "strategy-proposal"}, {"name": "discussion"}, {"name": "P0"}]
        post_calls: list = []

        def fake_urlopen(req, timeout=None):
            if req.method == "GET":
                return _make_response(existing)
            post_calls.append(json.loads(req.data.decode()))
            return _make_response({"name": "new"})

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            result = ensure_labels()

        assert post_calls == []  # 全部已存在，無需建立
        assert len(result) == 3

    def test_creates_missing_labels(self, monkeypatch):
        _mock_token(monkeypatch)
        created_names: list[str] = []

        def fake_urlopen(req, timeout=None):
            if req.method == "GET":
                return _make_response([])  # 沒有任何現有 label
            body = json.loads(req.data.decode())
            created_names.append(body["name"])
            return _make_response({"name": body["name"]})

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            ensure_labels()

        assert "strategy-proposal" in created_names
        assert "discussion" in created_names
        assert "P0" in created_names
