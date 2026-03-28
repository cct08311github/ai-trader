"""proposal_reviewer.py — LLM 自動審查 pending 策略提案（MiniMax M2.5）

掃描 strategy_proposals 中 status='pending' 的提案，
呼叫 MiniMax LLM 做快速審查，輸出 approve / reject + 理由，
更新 DB 並透過 Telegram 通知。

整合點（ticker_watcher 每輪掃盤後呼叫）：
    from openclaw.proposal_reviewer import auto_review_pending_proposals
    auto_review_pending_proposals(conn)

費用守衛：
    每日 LLM 呼叫次數上限由 LLM_DAILY_CALL_LIMIT 環境變數控制（預設 50）。
    超出後停止自動審查並寫入 incidents 表，Telegram 通知積壓狀況。
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import time
import uuid

log = logging.getLogger(__name__)

_MODEL = "MiniMax-M2.7"

# 每日 LLM 審查次數上限（可由環境變數覆蓋）
_LLM_DAILY_LIMIT: int = int(os.environ.get("LLM_DAILY_CALL_LIMIT", "50"))

_REVIEW_PROMPT_TMPL = """你是一位台股 Portfolio Manager，請快速審查以下減倉提案。

【持倉資訊】
標的：{symbol}（目前比重 {weight:.1%}）
建議減倉幅度：{reduce_pct:.1%}
觸發原因：{evidence}

【技術指標】
信號分數：{signal_score}　方向：{signal_direction}
近 5 日漲跌：{price_5d_change}　最新收盤：{latest_close}

【法人籌碼】
近 3 日法人淨買超：{institution_net_3d} 張

【近期決策績效】
{recent_decisions_summary}

【持倉概況】
{position_summary}

【審查要求】
- 以風控優先，集中度過高是主要風險
- 回傳嚴格的 JSON，欄位：
  {{
    "decision": "approve" 或 "reject",
    "confidence": 0.0–1.0,
    "reason": "50字內理由（繁體中文）"
  }}
- 不要有其他文字，只回傳 JSON
"""

_STRATEGY_REVIEW_PROMPT_TMPL = """你是台股 Portfolio Manager，審查以下策略建議。

【策略資訊】
方向：{direction}
建議：{proposed_value}
佐證：{evidence}

【持倉概況】
{position_summary}

【審查要求】
- 評估策略方向是否符合當前市場情況
- 回傳嚴格的 JSON，欄位：
  {{
    "decision": "approve" 或 "reject",
    "confidence": 0.0–1.0,
    "reason": "一句話說明理由（繁體中文）"
  }}
- 不要有其他文字，只回傳 JSON
"""

# Rules eligible for LLM review
_REVIEWABLE_RULES = {"POSITION_REBALANCE", "STRATEGY_DIRECTION"}


def _count_reviews_today(conn: sqlite3.Connection) -> int:
    """計算今日（台北時間）已完成的 LLM 審查次數。

    以 strategy_proposals.decided_at（ms epoch）為基準，
    today_start = 今日 00:00 Asia/Taipei → UTC epoch ms。
    """
    import datetime as _dt
    import zoneinfo as _zi
    tz = _zi.ZoneInfo("Asia/Taipei")
    today_start = _dt.datetime.now(tz).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    today_start_ms = int(today_start.timestamp() * 1000)
    row = conn.execute(
        "SELECT COUNT(*) FROM strategy_proposals "
        "WHERE decided_at >= ? AND status IN ('approved','rejected')",
        (today_start_ms,),
    ).fetchone()
    return int(row[0]) if row else 0


def _record_cost_guard_incident(
    conn: sqlite3.Connection,
    *,
    reviewed_today: int,
    pending_remaining: int,
) -> None:
    """將費用守衛觸發事件寫入 incidents 表。"""
    try:
        conn.execute(
            """INSERT INTO incidents
               (incident_id, ts, severity, source, code, detail_json, resolved)
               VALUES (?, datetime('now'), 'warn', 'proposal_reviewer',
                       'LLM_COST_GUARD', ?, 0)""",
            (
                str(uuid.uuid4()),
                json.dumps({
                    "reviewed_today": reviewed_today,
                    "pending_remaining": pending_remaining,
                    "daily_limit": _LLM_DAILY_LIMIT,
                }, ensure_ascii=True),
            ),
        )
        conn.commit()
    except Exception as e:  # noqa: BLE001
        log.warning("[proposal_reviewer] cost_guard incident 寫入失敗: %s", e)


def _position_weights(conn: sqlite3.Connection) -> dict[str, float]:
    try:
        rows = conn.execute(
            "SELECT symbol, quantity, current_price FROM positions WHERE quantity > 0"
        ).fetchall()
    except Exception:
        return {}

    total_value = sum((r[1] or 0) * (r[2] or 0) for r in rows)
    if total_value <= 0:
        return {}

    return {
        str(r[0]): (((r[1] or 0) * (r[2] or 0)) / total_value)
        for r in rows
        if r[0]
    }


def _build_position_summary(conn: sqlite3.Connection) -> str:
    try:
        rows = conn.execute(
            "SELECT symbol, quantity, avg_price, current_price, unrealized_pnl "
            "FROM positions WHERE quantity > 0 ORDER BY quantity * current_price DESC"
        ).fetchall()
        if not rows:
            return "（目前無持倉）"
        lines = []
        total = sum((r[1] or 0) * (r[3] or 0) for r in rows)
        for r in rows:
            val = (r[1] or 0) * (r[3] or 0)
            pct = val / total if total > 0 else 0
            lines.append(
                f"  {r[0]}: qty={r[1]} avg={r[2]:.1f} now={r[3]:.1f} "
                f"pnl={r[4]:.0f} weight={pct:.1%}"
            )
        return "\n".join(lines)
    except Exception:
        return "（持倉資料讀取失敗）"


def _build_review_context(conn: sqlite3.Connection, symbol: str) -> dict:
    """組裝技術指標、法人籌碼、近期決策等額外上下文，豐富 LLM 審查輸入。"""
    ctx: dict = {
        "signal_score": "N/A",
        "signal_direction": "N/A",
        "price_5d_change": "N/A",
        "latest_close": "N/A",
        "institution_net_3d": 0,
        "recent_decisions_summary": "（無近期決策紀錄）",
    }

    # 1. 技術指標（lm_signal_cache）
    try:
        row = conn.execute(
            """SELECT score, direction
               FROM lm_signal_cache
               WHERE symbol = ? AND expires_at > ?
               ORDER BY created_at DESC LIMIT 1""",
            (symbol, int(time.time() * 1000)),
        ).fetchone()
        if row:
            ctx["signal_score"] = f"{row[0]}/10"
            ctx["signal_direction"] = str(row[1])
    except Exception:
        pass

    # 2. 近 5 日價量趨勢（eod_prices）
    try:
        prices = conn.execute(
            """SELECT close FROM eod_prices
               WHERE symbol = ?
               ORDER BY trade_date DESC LIMIT 5""",
            (symbol,),
        ).fetchall()
        if len(prices) >= 2:
            closes = [r[0] for r in prices]
            ctx["price_5d_change"] = f"{((closes[0] / closes[-1]) - 1) * 100:+.1f}%"
            ctx["latest_close"] = f"{closes[0]:.1f}"
    except Exception:
        pass

    # 3. 法人籌碼（eod_institution_flows — 近 3 日）
    try:
        row = conn.execute(
            """SELECT COALESCE(SUM(foreign_net + sitc_net + dealer_net), 0)
               FROM eod_institution_flows
               WHERE symbol = ? AND trade_date >= date('now', '-3 days')""",
            (symbol,),
        ).fetchone()
        if row:
            ctx["institution_net_3d"] = int(row[0] or 0)
    except Exception:
        pass

    # 4. 近期決策績效（decisions — 最近 3 筆）
    try:
        decisions = conn.execute(
            """SELECT decision_type, result_pnl
               FROM decisions WHERE symbol = ?
               ORDER BY created_at DESC LIMIT 3""",
            (symbol,),
        ).fetchall()
        if decisions:
            parts = [
                f"{d[0]} PnL={d[1]:.1%}" if d[1] is not None else d[0]
                for d in decisions
            ]
            ctx["recent_decisions_summary"] = "、".join(parts)
    except Exception:
        pass

    return ctx


def _gemini_review(
    conn: sqlite3.Connection,
    symbol: str,
    weight: float,
    reduce_pct: float,
    evidence: str,
    position_summary: str,
) -> dict:
    """呼叫 MiniMax M2.7 審查 POSITION_REBALANCE 提案，回傳 {decision, confidence, reason}。"""
    from openclaw.llm_minimax import minimax_call

    ctx = _build_review_context(conn, symbol)
    prompt = _REVIEW_PROMPT_TMPL.format(
        symbol=symbol,
        weight=weight,
        reduce_pct=reduce_pct,
        evidence=evidence,
        position_summary=position_summary,
        **ctx,
    )
    result = minimax_call(_MODEL, prompt)
    return {k: v for k, v in result.items() if not k.startswith("_")}


def _strategy_direction_review(
    direction: str, proposed_value: str, evidence: str, position_summary: str
) -> dict:
    """呼叫 MiniMax M2.7 審查 STRATEGY_DIRECTION 提案，回傳 {decision, confidence, reason}。"""
    from openclaw.llm_minimax import minimax_call

    prompt = _STRATEGY_REVIEW_PROMPT_TMPL.format(
        direction=direction,
        proposed_value=proposed_value or "(無說明)",
        evidence=evidence or "(無佐證)",
        position_summary=position_summary,
    )
    result = minimax_call(_MODEL, prompt)
    return {k: v for k, v in result.items() if not k.startswith("_")}


def auto_review_pending_proposals(conn: sqlite3.Connection) -> int:
    """審查所有 pending proposals，核准/拒絕並傳送 Telegram 通知。

    每日 LLM 呼叫次數受 _LLM_DAILY_LIMIT 限制（預設 50，可由
    LLM_DAILY_CALL_LIMIT 環境變數覆蓋）。超出後停止審查、寫入
    incidents 表並透過 Telegram 通知積壓狀況。

    Returns:
        本次審查完成的 proposal 數量
    """
    rows = conn.execute(
        """SELECT proposal_id, generated_by, target_rule, supporting_evidence,
                  proposal_json
           FROM strategy_proposals
           WHERE status = 'pending'
             AND (expires_at IS NULL OR expires_at > ?)""",
        (int(time.time() * 1000),),
    ).fetchall()

    if not rows:
        return 0

    from openclaw.tg_notify import send_message
    position_summary = _build_position_summary(conn)
    live_weights = _position_weights(conn)
    reviewed = 0

    for proposal_id, generated_by, target_rule, evidence, proposal_json_str in rows:
        # ── 費用守衛：每筆審查前先檢查今日已用量 ──────────────────────────
        reviewed_today = _count_reviews_today(conn)
        if reviewed_today >= _LLM_DAILY_LIMIT:
            remaining = len(rows) - reviewed
            log.warning(
                "[proposal_reviewer] 今日 LLM 審查已達上限 %d，%d 筆 pending proposals 積壓",
                _LLM_DAILY_LIMIT, remaining,
            )
            _record_cost_guard_incident(
                conn, reviewed_today=reviewed_today, pending_remaining=remaining
            )
            try:
                send_message(
                    f"⚠️ <b>[費用守衛]</b> 今日 LLM 審查已達上限 {_LLM_DAILY_LIMIT} 次。\n"
                    f"尚有 {remaining} 筆 pending proposals 待審，將於明日自動恢復。\n"
                    f"如需立即審查，請至 Strategy 頁面手動處理。"
                )
            except Exception as _tg_e:  # noqa: BLE001
                log.warning("[proposal_reviewer] cost_guard Telegram 通知失敗: %s", _tg_e)
            break

        try:
            proposal = json.loads(proposal_json_str or "{}")

            # Skip rules not in reviewable set
            if target_rule not in _REVIEWABLE_RULES:
                log.info(
                    "[proposal_reviewer] skip non-reviewable proposal %s (%s/%s)",
                    proposal_id[:8], generated_by, target_rule,
                )
                continue

            if target_rule == "POSITION_REBALANCE":
                symbol = str(proposal.get("symbol", "")).strip()
                reduce_pct = float(proposal.get("reduce_pct", 0))
                weight = float(
                    proposal.get(
                        "current_weight",
                        proposal.get("weight", live_weights.get(symbol, 0)),
                    )
                )

                if not symbol or reduce_pct <= 0 or weight <= 0:
                    conn.execute(
                        "UPDATE strategy_proposals SET status=?, decided_at=? "
                        "WHERE proposal_id=?",
                        ("skipped", int(time.time() * 1000), proposal_id),
                    )
                    conn.commit()
                    log.info(
                        "[proposal_reviewer] skipped invalid proposal %s "
                        "(symbol=%r reduce_pct=%.4f weight=%.4f)",
                        proposal_id[:8], symbol, reduce_pct, weight,
                    )
                    continue

                result = _gemini_review(
                    conn=conn,
                    symbol=symbol, weight=weight, reduce_pct=reduce_pct,
                    evidence=evidence or "", position_summary=position_summary,
                )
                decision_label = "核准減倉" if result.get("decision") == "approve" else "拒絕"
                detail_line = f"建議減倉：{reduce_pct:.1%}　目前比重：{weight:.1%}"

            else:  # STRATEGY_DIRECTION
                committee_ctx = proposal.get("committee_context", {})
                arbiter = committee_ctx.get("arbiter", {})
                direction = str(arbiter.get("direction", proposal.get("direction", ""))).strip()
                proposed_value = str(proposal.get("proposed_value", "")).strip()
                symbol = str(proposal.get("symbol", "")).strip()

                result = _strategy_direction_review(
                    direction=direction,
                    proposed_value=proposed_value,
                    evidence=evidence or "",
                    position_summary=position_summary,
                )
                decision_label = "核准策略" if result.get("decision") == "approve" else "拒絕"
                detail_line = f"方向：{direction}"
                weight = 0.0
                reduce_pct = 0.0

            decision = result.get("decision", "reject").lower()
            confidence = float(result.get("confidence", 0))
            reason = result.get("reason", "")

            new_status = "approved" if decision == "approve" else "rejected"
            conn.execute(
                "UPDATE strategy_proposals SET status=?, decided_at=? "
                "WHERE proposal_id=?",
                (new_status, int(time.time() * 1000), proposal_id),
            )
            conn.commit()

            # Telegram 通知
            from openclaw.tg_approver import _fmt_symbol
            sym_display = _fmt_symbol(conn, symbol) if symbol else target_rule
            icon = "✅" if new_status == "approved" else "🚫"
            msg = (
                f"{icon} <b>[盤中策略審查]</b>\n"
                f"{'標的：<b>' + sym_display + '</b> | ' if symbol else ''}"
                f"規則：{target_rule}\n"
                f"決定：<b>{decision_label}</b>（信心 {confidence:.0%}）\n"
                f"{detail_line}\n"
                f"理由：{reason}"
            )
            send_message(msg)
            log.info("[proposal_reviewer] %s → %s (conf=%.2f) %s",
                     proposal_id[:8], new_status, confidence, reason)
            reviewed += 1

        except Exception as e:
            log.warning("[proposal_reviewer] proposal %s 審查失敗: %s", proposal_id[:8], e)

    return reviewed
