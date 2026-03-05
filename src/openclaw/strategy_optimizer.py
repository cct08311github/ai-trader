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


class OptimizationGateway:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

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
            adj = self._adjust_param(
                "trailing_pct",
                delta=+_TRAILING_PCT_DELTA,   # 收緊（增大 trailing）
                rationale=f"win_rate={metrics.win_rate:.1%} < {_LOW_WIN_RATE_THRESHOLD:.0%}",
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
            "SELECT value FROM risk_limits WHERE name=?", (param_key,)
        ).fetchone()
        if current is None:
            return None
        old_val = current["value"]

        # 計算新值（受 delta 和邊界限制）
        raw_new = old_val + delta
        new_val = max(bounds["min_val"], min(bounds["max_val"], raw_new))

        # weekly_max_delta 檢查
        actual_delta = abs(new_val - old_val)
        if actual_delta > bounds["weekly_max_delta"]:
            new_val = old_val + (bounds["weekly_max_delta"] * (1 if delta > 0 else -1))
            new_val = max(bounds["min_val"], min(bounds["max_val"], new_val))

        if abs(new_val - old_val) < 1e-6:
            return None  # 無實質變化

        # 執行調整
        self.conn.execute(
            "UPDATE risk_limits SET value=?, updated_at=? WHERE name=?",
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
            response = self._call_gemini(context)
            return self._parse_proposals(response)
        except Exception as e:
            log.warning("[ReflectionAgent] Gemini 反思失敗，跳過：%s", e)
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
            if metrics.win_rate is not None
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

    def _call_gemini(self, prompt: str) -> str:
        from openclaw.llm_gemini import call_gemini  # type: ignore
        return call_gemini(prompt)

    def _parse_proposals(self, response: str) -> list[dict]:
        import json
        try:
            data = json.loads(response)
            return data.get("proposals", [])
        except (json.JSONDecodeError, AttributeError):
            log.warning("[ReflectionAgent] 無法解析 Gemini 回應")
            return []
