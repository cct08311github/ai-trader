# tests/test_check_approved_issues.py
"""check_approved_issues.py 單元測試

覆蓋：
- parse_signal_params — 從 issue 文字擷取策略參數
- parse_symbols — 擷取台股代號
- evaluate_backtest — 門檻判斷邏輯
- format_backtest_comment — 報告格式化
- save_results_state — 結果寫入
- main() — dry-run 整合測試（不呼叫 GitHub API 或 backtest engine）
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# 確保 tools/ 可匯入
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import check_approved_issues as cai


# ─────────────────────────── parse_signal_params ─────────────────────────────

class TestParseSignalParams:
    def test_parses_ma_params(self):
        text = "建議調整 ma_short: 10 和 ma_long: 30"
        result = cai.parse_signal_params(text)
        assert result["ma_short"] == 10
        assert result["ma_long"] == 30

    def test_parses_rsi_period(self):
        text = "rsi_period=21 rsi_entry_max=65.5"
        result = cai.parse_signal_params(text)
        assert result["rsi_period"] == 21
        assert result["rsi_entry_max"] == 65.5

    def test_parses_stop_loss_take_profit(self):
        text = "stop_loss_pct: 0.05  take_profit_pct=0.08"
        result = cai.parse_signal_params(text)
        assert result["stop_loss_pct"] == pytest.approx(0.05)
        assert result["take_profit_pct"] == pytest.approx(0.08)

    def test_parses_trailing_params(self):
        text = "trailing_pct: 0.07 trailing_pct_tight: 0.04 trailing_profit_threshold: 0.60"
        result = cai.parse_signal_params(text)
        assert result["trailing_pct"] == pytest.approx(0.07)
        assert result["trailing_pct_tight"] == pytest.approx(0.04)
        assert result["trailing_profit_threshold"] == pytest.approx(0.60)

    def test_empty_text_returns_empty(self):
        assert cai.parse_signal_params("") == {}

    def test_irrelevant_text_returns_empty(self):
        assert cai.parse_signal_params("今天天氣很好，市場平靜") == {}

    def test_case_insensitive(self):
        result = cai.parse_signal_params("MA_SHORT=8 RSI_PERIOD=12")
        assert result["ma_short"] == 8
        assert result["rsi_period"] == 12


# ─────────────────────────── parse_symbols ───────────────────────────────────

class TestParseSymbols:
    def test_parses_taiwan_stock_codes(self):
        text = "測試股票 2330 台積電, 2317 鴻海, 2454"
        result = cai.parse_symbols(text)
        assert "2330" in result
        assert "2317" in result
        assert "2454" in result

    def test_deduplicates(self):
        result = cai.parse_symbols("2330 2330 2330")
        assert result.count("2330") == 1

    def test_empty_returns_empty(self):
        assert cai.parse_symbols("沒有任何代號") == []

    def test_filters_short_numbers(self):
        # 2 位數或 3 位數不應匹配（< 4 位）
        result = cai.parse_symbols("買 99 張，代號 123")
        assert "99" not in result
        assert "123" not in result


# ─────────────────────────── evaluate_backtest ───────────────────────────────

class TestEvaluateBacktest:
    def _metrics(self, **overrides) -> dict:
        base = {
            "total_trades": 10,
            "sharpe_ratio": 0.8,
            "max_drawdown_pct": 10.0,
            "win_rate": 55.0,
            "profit_factor": 1.5,
            "total_return_pct": 12.0,
            "annualized_return_pct": 15.0,
            "avg_holding_days": 8.0,
            "symbols": ["2330"],
            "start_date": "2025-09-01",
            "end_date": "2026-03-01",
            "signal_params": {},
        }
        base.update(overrides)
        return base

    def test_passing_metrics(self):
        passed, _ = cai.evaluate_backtest(self._metrics())
        assert passed is True

    def test_fails_on_low_trade_count(self):
        passed, reason = cai.evaluate_backtest(self._metrics(total_trades=3))
        assert passed is False
        assert "交易次數" in reason

    def test_fails_on_low_sharpe(self):
        passed, reason = cai.evaluate_backtest(self._metrics(sharpe_ratio=0.3))
        assert passed is False
        assert "Sharpe" in reason

    def test_fails_on_high_drawdown(self):
        passed, reason = cai.evaluate_backtest(self._metrics(max_drawdown_pct=25.0))
        assert passed is False
        assert "回撤" in reason

    def test_multiple_failures_combined(self):
        passed, reason = cai.evaluate_backtest(
            self._metrics(total_trades=2, sharpe_ratio=0.1, max_drawdown_pct=30.0)
        )
        assert passed is False
        # 多個失敗原因以分號連接
        assert "；" in reason


# ─────────────────────────── format_backtest_comment ─────────────────────────

class TestFormatBacktestComment:
    def _metrics(self) -> dict:
        return {
            "symbols": ["2330", "2317"],
            "start_date": "2025-09-01",
            "end_date": "2026-03-01",
            "signal_params": {},
            "total_trades": 12,
            "total_return_pct": 8.5,
            "annualized_return_pct": 17.0,
            "sharpe_ratio": 0.92,
            "max_drawdown_pct": 9.5,
            "win_rate": 58.3,
            "profit_factor": 1.8,
            "avg_holding_days": 7.2,
        }

    def test_contains_issue_number(self):
        comment = cai.format_backtest_comment(
            42, self._metrics(), {}, True, "通過所有門檻"
        )
        assert "#42" in comment

    def test_passed_shows_checkmark(self):
        comment = cai.format_backtest_comment(
            1, self._metrics(), {}, True, "通過所有門檻"
        )
        assert "✅" in comment
        assert "PASSED" in comment

    def test_failed_shows_x(self):
        comment = cai.format_backtest_comment(
            1, self._metrics(), {}, False, "Sharpe Ratio 過低"
        )
        assert "❌" in comment
        assert "FAILED" in comment

    def test_includes_metrics_table(self):
        comment = cai.format_backtest_comment(
            1, self._metrics(), {}, True, "ok"
        )
        assert "Sharpe Ratio" in comment
        assert "最大回撤" in comment
        assert "0.92" in comment

    def test_includes_extracted_params(self):
        params = {"ma_short": 10, "rsi_period": 21}
        comment = cai.format_backtest_comment(
            1, self._metrics(), params, True, "ok"
        )
        assert "ma_short" in comment
        assert "10" in comment


# ─────────────────────────── save_results_state ──────────────────────────────

class TestSaveResultsState:
    def test_writes_json_file(self, tmp_path):
        state_file = tmp_path / "coder_agent_results.json"
        results = [{"issue_number": 10, "passed": True}]
        cai.save_results_state(results, state_path=state_file)

        assert state_file.exists()
        data = json.loads(state_file.read_text())
        assert "generated_at" in data
        assert data["results"] == results

    def test_creates_parent_dir(self, tmp_path):
        state_file = tmp_path / "subdir" / "results.json"
        cai.save_results_state([], state_path=state_file)
        assert state_file.exists()

    def test_overwrites_existing(self, tmp_path):
        state_file = tmp_path / "r.json"
        cai.save_results_state([{"issue_number": 1}], state_path=state_file)
        cai.save_results_state([{"issue_number": 2}], state_path=state_file)
        data = json.loads(state_file.read_text())
        assert data["results"][0]["issue_number"] == 2


# ─────────────────────────── main() dry-run ──────────────────────────────────

class TestMainDryRun:
    def _mock_issue(self, number: int = 100) -> dict:
        return {
            "number": number,
            "title": f"[Test] Adjust ma_short=8 ma_long=25 for 2330",
            "body": "修改均線參數：ma_short: 8, ma_long: 25\n標的：2330",
        }

    def test_dry_run_no_token_succeeds(self):
        with patch.object(cai, "fetch_approved_issues", return_value=[]):
            rc = cai.main(["--dry-run", "--token", "fake"])
        assert rc == 0

    def test_dry_run_with_issues_runs_backtest(self, tmp_path):
        issue = self._mock_issue(201)

        fake_metrics = {
            "symbols": ["2330"],
            "start_date": "2025-09-01",
            "end_date": "2026-03-01",
            "signal_params": {"ma_short": 8},
            "total_trades": 8,
            "total_return_pct": 5.0,
            "annualized_return_pct": 10.0,
            "sharpe_ratio": 0.75,
            "max_drawdown_pct": 12.0,
            "win_rate": 62.5,
            "profit_factor": 2.0,
            "avg_holding_days": 6.0,
        }

        with patch.object(cai, "fetch_approved_issues", return_value=[issue]), \
             patch.object(cai, "run_backtest_for_issue", return_value=fake_metrics), \
             patch.object(cai, "post_issue_comment") as mock_post:

            rc = cai.main(["--dry-run", "--token", "fake", "--db", str(tmp_path / "fake.db")])

        assert rc == 0
        # dry-run: should NOT post to GitHub
        mock_post.assert_not_called()

    def test_no_approved_issues_returns_0(self):
        with patch.object(cai, "fetch_approved_issues", return_value=[]):
            rc = cai.main(["--dry-run", "--token", "fake"])
        assert rc == 0

    def test_no_approved_issues_clears_state_in_non_dry_run(self):
        with patch.object(cai, "fetch_approved_issues", return_value=[]), \
             patch.object(cai, "save_results_state") as mock_save:
            rc = cai.main(["--token", "fake"])
        assert rc == 0
        mock_save.assert_called_once_with([])

    def test_github_api_failure_returns_1(self):
        import urllib.error
        with patch.object(
            cai, "fetch_approved_issues",
            side_effect=urllib.error.HTTPError(None, 401, "Unauthorized", {}, None)
        ):
            rc = cai.main(["--dry-run", "--token", "bad"])
        assert rc == 1

    def test_missing_token_without_dry_run_returns_1(self):
        rc = cai.main(["--token", ""])
        assert rc == 1
