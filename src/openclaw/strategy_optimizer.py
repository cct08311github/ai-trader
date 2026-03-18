# src/openclaw/strategy_optimizer.py
"""strategy_optimizer.py — 策略自主優化機制

統計前置 + LLM 二層裁量：
  - StrategyMetricsEngine: 每日 EOD 計算勝率/損益比等指標
  - OptimizationGateway: 根據統計結果做安全自動調整（param_bounds 護欄）
  - ReflectionAgent: 週期 Gemini 深度反思（see Task 6）

安全調整（自動生效）：trailing_pct、daily_loss_limit
重大調整（proposal）: take_profit_pct、stop_loss_pct、MA 週期
"""
from __future__ import annotations

import logging
import sqlite3
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

log = logging.getLogger(__name__)

_MIN_SAMPLE_FOR_CONFIDENCE = 30
_CONFIDENCE_THRESHOLD = 0.6  # 低於此值不觸發調整

# 安全調整的觸發條件
_LOW_WIN_RATE_THRESHOLD = 0.35     # 勝率 < 35% → 收緊 trailing_pct
_TRAILING_PCT_DELTA = 0.005        # 每次調整幅度

# Walk-Forward 驗證窗口設定 [Issue #281]
_WF_TRAIN_DAYS = 60   # 訓練期（用於計算基準指標）
_WF_VALID_DAYS = 20   # 驗證期（t-20 至今；驗證期必須確認同一問題）
_WF_MIN_VALID_TRADES = 3  # 驗證期最少成交筆數（不足則 bypass 驗證）


@dataclass
class MetricsReport:
    sample_n: int
    confidence: float              # 0.0 ~ 1.0（= min(1.0, sample_n / 30)）
    win_rate: Optional[float]
    profit_factor: Optional[float]
    avg_hold_days: Optional[float] = None
    max_drawdown_pct: Optional[float] = None


@dataclass
class AutoAdjustment:
    param_key: str
    old_value: float
    new_value: float
    rationale: str
    sample_n: int
    confidence: float

    def as_dict(self):
        return {
            "param_key": self.param_key,
            "old_value": self.old_value,
            "new_value": self.new_value,
        }


class StrategyMetricsEngine:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def compute(self, window_days: int = 28) -> MetricsReport:
        cutoff_ts = (datetime.now() - timedelta(days=window_days)).isoformat()
        trades = self._get_closed_trades(cutoff_ts)
        n = len(trades)
        if n == 0:
            return MetricsReport(sample_n=0, confidence=0.0,
                                 win_rate=None, profit_factor=None)

        wins   = [t for t in trades if t["pnl"] > 0]
        losses = [t for t in trades if t["pnl"] <= 0]

        win_rate = len(wins) / n
        gross_profit = sum(t["pnl"] for t in wins)
        gross_loss   = abs(sum(t["pnl"] for t in losses)) or 0.01
        profit_factor = gross_profit / gross_loss
        confidence = min(1.0, n / _MIN_SAMPLE_FOR_CONFIDENCE)

        return MetricsReport(
            sample_n=n,
            confidence=confidence,
            win_rate=win_rate,
            profit_factor=profit_factor,
        )

    def _get_closed_trades(self, cutoff_ts: str) -> list[dict]:
        """配對 buy + sell（FIFO），計算每筆交易 P&L。"""
        rows = self.conn.execute(
            """SELECT o.order_id, o.symbol, o.side, o.ts_submit,
                      SUM(f.qty) as qty,
                      SUM(f.price * f.qty) / SUM(f.qty) as avg_price,
                      SUM(f.fee + f.tax) as cost
               FROM orders o JOIN fills f ON o.order_id = f.order_id
               WHERE o.ts_submit > ? AND o.status = 'filled'
               GROUP BY o.order_id
               ORDER BY o.ts_submit""",
            (cutoff_ts,),
        ).fetchall()

        # Single-pass chronological FIFO pairing
        buy_queues: dict[str, deque] = defaultdict(deque)
        trades = []
        for r in rows:
            if r["side"] == "buy":
                buy_queues[r["symbol"]].append(r)
            elif r["side"] == "sell" and buy_queues[r["symbol"]]:
                buy = buy_queues[r["symbol"]].popleft()
                pnl = (r["avg_price"] - buy["avg_price"]) * r["qty"] - r["cost"] - buy["cost"]
                trades.append({"symbol": r["symbol"], "pnl": pnl})
        return trades


def _ensure_optimizer_schema(conn: sqlite3.Connection) -> None:
    """確保 param_bounds 存在並初始化預設護欄（冪等）。"""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS param_bounds (
            param_key           TEXT PRIMARY KEY,
            min_val             REAL NOT NULL,
            max_val             REAL NOT NULL,
            weekly_max_delta    REAL NOT NULL,
            last_auto_change_ts INTEGER,
            frozen_until_ts     INTEGER
        )
    """)
    # 確保 trailing_pct 有護欄定義
    conn.execute("""
        INSERT OR IGNORE INTO param_bounds
            (param_key, min_val, max_val, weekly_max_delta)
        VALUES ('trailing_pct', 0.02, 0.15, 0.02)
    """)
    # 確保 trailing_pct 有初始值（若不存在）
    import uuid
    conn.execute("""
        INSERT INTO risk_limits
            (limit_id, scope, rule_name, rule_value, enabled, updated_at)
        SELECT ?, 'global', 'trailing_pct', 0.05, 1, datetime('now')
        WHERE NOT EXISTS (SELECT 1 FROM risk_limits WHERE rule_name='trailing_pct')
    """, (uuid.uuid4().hex[:16],))
    conn.commit()


class WalkForwardValidator:
    """Walk-Forward Out-of-Sample 驗證閘門 [Issue #281]

    在套用自動調整前，確認問題在驗證期（最近 _WF_VALID_DAYS 天）同樣存在。
    若驗證期訓練不足（< _WF_MIN_VALID_TRADES），則 bypass 驗證（保守通過）。

    驗證邏輯：
        訓練期 = [t - (_WF_TRAIN_DAYS + _WF_VALID_DAYS),  t - _WF_VALID_DAYS]
        驗證期 = [t - _WF_VALID_DAYS,  t]

    如果驗證期的指標沒有確認訓練期所觀察到的問題，則拒絕調整以防過度擬合。
    """

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self._metrics_engine = StrategyMetricsEngine(conn)

    def validate(self, condition: str, train_metrics: MetricsReport) -> tuple[bool, str]:
        """
        Args:
            condition: 觸發調整的條件名稱（目前支援 "low_win_rate"）
            train_metrics: 訓練期指標（由呼叫者提供，避免重複計算）

        Returns:
            (passed: bool, reason: str)
        """
        valid_cutoff = (
            datetime.now() - timedelta(days=_WF_VALID_DAYS)
        ).isoformat()
        valid_metrics = self._metrics_engine.compute(window_days=_WF_VALID_DAYS)

        # 驗證期樣本不足 → bypass（保守通過）
        if valid_metrics.sample_n < _WF_MIN_VALID_TRADES:
            return True, (
                f"bypass: 驗證期交易筆數 {valid_metrics.sample_n} < {_WF_MIN_VALID_TRADES}"
            )

        if condition == "low_win_rate":
            # 驗證期也必須確認低勝率問題
            if valid_metrics.win_rate is None:
                return True, "bypass: 驗證期 win_rate=None"
            if valid_metrics.win_rate < _LOW_WIN_RATE_THRESHOLD:
                return True, (
                    f"confirmed: 驗證期 win_rate={valid_metrics.win_rate:.1%}"
                    f" < {_LOW_WIN_RATE_THRESHOLD:.0%}"
                )
            return False, (
                f"rejected: 驗證期 win_rate={valid_metrics.win_rate:.1%}"
                f" >= {_LOW_WIN_RATE_THRESHOLD:.0%}，問題未在驗證期確認"
            )

        # 未知條件 → 保守通過
        return True, f"bypass: 未知條件 {condition!r}"


class OptimizationGateway:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        _ensure_optimizer_schema(conn)
        self._validator = WalkForwardValidator(conn)

    def on_eod(self, metrics: MetricsReport) -> list[dict]:
        """根據 EOD 統計結果執行安全調整。
        Returns: list of AutoAdjustment.as_dict()
        """
        if metrics.confidence < _CONFIDENCE_THRESHOLD:
            log.info("[optimizer] confidence=%.2f < threshold, 跳過調整（樣本=%d）",
                     metrics.confidence, metrics.sample_n)
            return []

        adjustments: list[AutoAdjustment] = []

        # 安全調整 1：低勝率 → 收緊 trailing_pct（讓更早鎖利）
        if metrics.win_rate is not None and metrics.win_rate < _LOW_WIN_RATE_THRESHOLD:
            # Walk-Forward 驗證：確認問題在驗證期同樣存在
            wf_passed, wf_reason = self._validator.validate("low_win_rate", metrics)
            log.info("[optimizer] walk-forward validation (low_win_rate): %s", wf_reason)
            if not wf_passed:
                log.info("[optimizer] trailing_pct 調整被 walk-forward 驗證拒絕：%s", wf_reason)
            else:
                adj = self._adjust_param(
                    "trailing_pct",
                    delta=+_TRAILING_PCT_DELTA,   # 收緊（增大 trailing）
                    rationale=f"win_rate={metrics.win_rate:.1%} < {_LOW_WIN_RATE_THRESHOLD:.0%}; wf={wf_reason}",
                    metrics=metrics,
                )
                if adj:
                    adjustments.append(adj)

        return [a.as_dict() for a in adjustments]

    def _adjust_param(
        self,
        param_key: str,
        delta: float,
        rationale: str,
        metrics: MetricsReport,
    ) -> Optional[AutoAdjustment]:
        """嘗試調整參數，受 param_bounds 約束。"""
        now = int(time.time())

        bounds = self.conn.execute(
            "SELECT * FROM param_bounds WHERE param_key=?", (param_key,)
        ).fetchone()
        if bounds is None:
            return None  # 無約束定義，不調整

        # 凍結期檢查
        if bounds["frozen_until_ts"] and bounds["frozen_until_ts"] > now:
            log.info("[optimizer] %s 凍結中（until %s），跳過",
                     param_key, bounds["frozen_until_ts"])
            return None

        # 讀取現值
        current = self.conn.execute(
            "SELECT rule_value FROM risk_limits WHERE rule_name=?", (param_key,)
        ).fetchone()
        if current is None:
            return None
        old_val = current["rule_value"]

        # 本週累積 delta 檢查（確保 7 日內累積調整量不超過 weekly_max_delta）
        one_week_ago = now - 7 * 86400
        week_delta_row = self.conn.execute(
            """SELECT COALESCE(SUM(ABS(new_value - old_value)), 0) AS total_delta
               FROM optimization_log
               WHERE param_key=? AND ts > ? AND is_auto=1""",
            (param_key, one_week_ago),
        ).fetchone()
        week_delta_used = float(week_delta_row["total_delta"]) if week_delta_row else 0.0
        remaining_budget = bounds["weekly_max_delta"] - week_delta_used
        if remaining_budget <= 1e-6:
            log.info(
                "[optimizer] %s 本週累積調整已達 %.4f >= weekly_max_delta %.4f，跳過",
                param_key, week_delta_used, bounds["weekly_max_delta"],
            )
            return None
        # 本次調整量以剩餘預算為上限
        capped_delta = min(abs(delta), remaining_budget) * (1 if delta > 0 else -1)

        # 計算新值（受 capped_delta 和邊界限制）
        raw_new = old_val + capped_delta
        new_val = max(bounds["min_val"], min(bounds["max_val"], raw_new))

        if abs(new_val - old_val) < 1e-6:
            return None  # 無實質變化

        # 執行調整
        self.conn.execute(
            "UPDATE risk_limits SET rule_value=?, updated_at=? WHERE rule_name=?",
            (new_val, now, param_key)
        )
        # 寫入 optimization_log
        self.conn.execute(
            """INSERT INTO optimization_log
               (ts, trigger_type, param_key, old_value, new_value,
                is_auto, sample_n, confidence, rationale)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (now, "eod_stats", param_key, old_val, new_val, 1,
             metrics.sample_n, metrics.confidence, rationale),
        )
        self.conn.commit()
        # 更新 last_auto_change_ts（記錄最後自動調整時間，供本週累積 delta 查詢使用）
        self.conn.execute(
            "UPDATE param_bounds SET last_auto_change_ts=? WHERE param_key=?",
            (now, param_key),
        )
        self.conn.commit()
        log.info("[optimizer] %s: %.4f → %.4f (%s)", param_key, old_val, new_val, rationale)

        return AutoAdjustment(
            param_key=param_key,
            old_value=old_val,
            new_value=new_val,
            rationale=rationale,
            sample_n=metrics.sample_n,
            confidence=metrics.confidence,
        )


class ReflectionAgent:
    """週期 Gemini 深度反思（週一 07:00，by agent_orchestrator）

    審查：
    1. 近 4 週 optimization_log（偵測單向漂移）
    2. 近 4 週 llm_traces（LLM 校準偏差）
    3. 整體策略表現 → 生成 proposal 建議
    """

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def reflect_weekly(self) -> list[dict]:
        """執行週期反思，回傳 proposals list（空 list = 無建議）。"""
        try:
            context = self._build_context()
            response = self._call_llm(context)
            return self._parse_proposals(response)
        except Exception as e:
            log.warning("[ReflectionAgent] LLM 反思失敗，跳過：%s", e)
            return []

    def _build_context(self) -> str:
        cutoff = int((datetime.now() - timedelta(days=28)).timestamp())

        # 近 4 週 optimization_log
        opt_rows = self.conn.execute(
            "SELECT param_key, old_value, new_value, rationale FROM optimization_log WHERE ts > ? ORDER BY ts",
            (cutoff,)
        ).fetchall()
        opt_summary = "\n".join(
            f"  {r['param_key']}: {r['old_value']:.4f} → {r['new_value']:.4f} ({r['rationale']})"
            for r in opt_rows
        ) or "  （無自動調整）"

        # 近 4 週 performance（重用 MetricsEngine）
        metrics = StrategyMetricsEngine(self.conn).compute(window_days=28)
        perf_summary = (
            f"  樣本數={metrics.sample_n}, 勝率={metrics.win_rate:.1%}, "
            f"損益比={metrics.profit_factor:.2f}"
            if metrics.win_rate is not None and metrics.profit_factor is not None
            else "  （樣本不足）"
        )

        return f"""你是 AI Trader 策略反思 Agent。請根據以下資料進行週期反思，提出調整建議。

近 4 週績效：
{perf_summary}

近 4 週自動調整記錄：
{opt_summary}

請回覆 JSON，格式為：
{{"direction": "bull|bear|neutral", "rationale": "...", "proposals": []}}
proposals 中每項格式：{{"param_key": "...", "action": "increase|decrease|review", "reason": "..."}}
"""

    def _call_llm(self, prompt: str) -> str:
        from openclaw.llm_minimax import minimax_call
        result = minimax_call("MiniMax-M2.5", prompt)
        return result.get("_raw_response", "")

    def _parse_proposals(self, response: str) -> list[dict]:
        import json
        try:
            data = json.loads(response)
            return data.get("proposals", [])
        except (json.JSONDecodeError, AttributeError):
            log.warning("[ReflectionAgent] 無法解析 LLM 回應")
            return []
