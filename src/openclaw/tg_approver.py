"""tg_approver.py — Telegram 策略提案通知（URL 按鈕版）

功能：
    - notify_pending_proposals(conn)  : 掃描 pending 提案，發 Telegram URL 按鈕通知
    - poll_approval_callbacks(conn)   : no-op（保留介面相容性，URL 按鈕不需要 polling）

URL 按鈕方案說明：
    inline keyboard 的 callback_data 按鈕會產生 callback_query update，
    與 OpenClaw gateway 的 getUpdates 競爭同一個 bot token，導致 gateway
    優先消費並路由給 LLM agent，tg_approver 永遠無法收到。
    改用 url 按鈕：點擊直接在瀏覽器開啟 ai-trader API（Tailscale 可達），
    API 端點更新 DB 並透過 Telegram 回送確認，完全繞過 callback_query。

狀態持久化：
    working_memory 表，scope='tg_approver'
      key='notified_ids'   → JSON 陣列，已發通知的 proposal_id
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import urllib.request
import uuid

log = logging.getLogger(__name__)

_DEFAULT_CHAT_ID = "1017252031"
_NOTIFIABLE_RULES = {"POSITION_REBALANCE", "SECTOR_FOCUS"}


# ── 內部工具 ──────────────────────────────────────────────────────────────────

def _token() -> str:
    return os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()


def _chat_id() -> str:
    return os.environ.get("TELEGRAM_CHAT_ID", _DEFAULT_CHAT_ID)


def _symbol_name(conn: sqlite3.Connection, symbol: str) -> str:
    """查 eod_prices 取得股票名稱，找不到就回傳 symbol 本身。"""
    try:
        row = conn.execute(
            "SELECT name FROM eod_prices WHERE symbol=? AND name IS NOT NULL"
            " ORDER BY trade_date DESC LIMIT 1",
            (symbol,),
        ).fetchone()
        name = row["name"] if row else None
        return name if name and name != symbol else symbol
    except Exception:
        return symbol


def _fmt_symbol(conn: sqlite3.Connection, symbol: str) -> str:
    """回傳 '3008 大立光' 或單獨 '3008'（若查無名稱）。"""
    if not symbol:
        return symbol
    name = _symbol_name(conn, symbol)
    return f"{symbol} {name}" if name != symbol else symbol


def _wm_get(conn: sqlite3.Connection, key: str):
    """從 working_memory (scope='tg_approver') 讀取 JSON 值，找不到回傳 None。"""
    row = conn.execute(
        "SELECT value_json FROM working_memory"
        " WHERE scope='tg_approver' AND key=?",
        (key,),
    ).fetchone()
    return json.loads(row["value_json"]) if row else None


def _wm_set(conn: sqlite3.Connection, key: str, value) -> None:
    """Upsert working_memory (scope='tg_approver', key=key)。"""
    now_ms = "CAST(strftime('%s','now') AS INTEGER)*1000"
    wm_id = f"tg_approver:{key}"
    conn.execute(
        f"""INSERT INTO working_memory
               (wm_id, session_date, scope, key, value_json, importance, created_at, updated_at)
             VALUES (?, date('now','+8 hours'), 'tg_approver', ?, ?, 3,
                     {now_ms}, {now_ms})
             ON CONFLICT(wm_id) DO UPDATE SET
               value_json=excluded.value_json,
               updated_at={now_ms}""",
        (wm_id, key, json.dumps(value)),
    )
    conn.commit()


def _answer_callback(token: str, callback_query_id: str, text: str) -> None:
    """回應 Telegram callback_query，消除按鈕 loading 圈。"""
    url = f"https://api.telegram.org/bot{token}/answerCallbackQuery"
    payload = json.dumps({
        "callback_query_id": callback_query_id,
        "text": text,
    }).encode()
    try:
        req = urllib.request.Request(
            url, data=payload,
            headers={"Content-Type": "application/json"},
        )
        urllib.request.urlopen(req, timeout=5)
    except Exception as e:
        log.debug("answerCallbackQuery failed: %s", e)


# ── 公開 API ──────────────────────────────────────────────────────────────────

def _extract_symbol(proposed_value: str, proposal_json_str: str) -> str:
    """從 proposal_json 或 proposed_value 文字中提取股票代號。"""
    # 先試 proposal_json
    try:
        pj = json.loads(proposal_json_str or "{}")
        sym = pj.get("symbol", "")
        if sym:
            return sym
    except Exception:
        pass
    # 從純文字用 regex 找 4 位數字代號
    import re
    m = re.search(r"\b(\d{4})\b", proposed_value or "")
    return m.group(1) if m else ""


def _get_position_context(conn: sqlite3.Connection, symbol: str) -> str:
    """查 positions 表，回傳持倉摘要文字（比重 + 損益）。"""
    if not symbol:
        return ""
    try:
        row = conn.execute(
            "SELECT quantity, avg_price, current_price, unrealized_pnl "
            "FROM positions WHERE symbol=? AND quantity>0",
            (symbol,),
        ).fetchone()
        if not row:
            return ""
        total_val = conn.execute(
            "SELECT SUM(quantity*current_price) FROM positions WHERE quantity>0"
        ).fetchone()[0] or 1
        pos_val = (row["quantity"] or 0) * (row["current_price"] or 0)
        weight = pos_val / total_val * 100
        pnl = row["unrealized_pnl"] or 0
        pnl_sign = "+" if pnl >= 0 else ""
        return f"持倉 {weight:.1f}%　損益 {pnl_sign}{pnl:,.0f}"
    except Exception:
        return ""


def notify_pending_proposals(conn: sqlite3.Connection) -> int:
    """掃描 pending 提案，對尚未通知的發送 Telegram inline 訊息。

    Returns:
        發送通知的數量（0 表示無新提案或 token 未設定）
    """
    from openclaw.tg_notify import send_message_with_buttons  # lazy import

    tok = _token()
    if not tok:
        return 0

    notified: set = set(_wm_get(conn, "notified_ids") or [])
    rows = conn.execute(
        """SELECT proposal_id, target_rule, proposed_value,
                  supporting_evidence, confidence, proposal_json
             FROM strategy_proposals
            WHERE status='pending'
              AND target_rule IN ('POSITION_REBALANCE', 'SECTOR_FOCUS')
            ORDER BY created_at DESC""",
    ).fetchall()

    sent = 0
    for row in rows:
        pid = row["proposal_id"]
        if pid in notified:
            continue

        rule = row["target_rule"]
        conf = row["confidence"] or 0.0
        proposed_value = (row["proposed_value"] or "").strip()
        evidence = (row["supporting_evidence"] or "").strip()

        # 提取標的代號
        symbol = _extract_symbol(proposed_value, row["proposal_json"] or "")
        sym_display = _fmt_symbol(conn, symbol) if symbol else ""

        # 持倉現況
        pos_ctx = _get_position_context(conn, symbol) if symbol else ""

        emoji = "🔄" if rule == "POSITION_REBALANCE" else "🎯"
        lines = [
            f"{emoji} <b>策略提案審查</b>",
            f"<b>類型</b>：{rule}",
        ]
        if sym_display:
            lines.append(f"<b>標的</b>：{sym_display}")
        if pos_ctx:
            lines.append(f"<b>現況</b>：{pos_ctx}")

        # 建議動作（proposed_value 直接顯示，最多 120 字）
        action_text = proposed_value[:120] + ("…" if len(proposed_value) > 120 else "")
        lines.append(f"\n📋 <b>建議</b>：{action_text}")

        # 理由（supporting_evidence，最多 200 字）
        if evidence:
            ev_text = evidence[:200] + ("…" if len(evidence) > 200 else "")
            lines.append(f"\n💡 <b>理由</b>：{ev_text}")

        lines.append(f"\n信心度：{conf:.0%}　<i>ID：{pid[:8]}…</i>")

        # URL 按鈕：點擊開瀏覽器呼叫 api 端點，不產生 callback_query
        base = os.environ.get("AI_TRADER_API_URL", "https://mac-mini.tailde842d.ts.net:8080")
        auth = os.environ.get("AUTH_TOKEN", "")
        buttons = [[
            {"text": "✅ 核准", "url": f"{base}/api/strategy/proposals/{pid}/approve?token={auth}"},
            {"text": "🚫 拒絕", "url": f"{base}/api/strategy/proposals/{pid}/reject?token={auth}"},
        ]]

        ok = send_message_with_buttons("\n".join(lines), buttons)
        if ok:
            notified.add(pid)
            sent += 1
            log.info("[tg_approver] Notified proposal %s (%s)", pid[:8], rule)

    if sent > 0:
        _wm_set(conn, "notified_ids", list(notified))

    return sent


def poll_approval_callbacks(conn: sqlite3.Connection) -> int:
    """No-op — URL 按鈕方案不需要 polling。

    保留此函式介面以維持 ticker_watcher 相容性。
    核准/拒絕由 api/strategy/proposals/{id}/approve|reject 端點處理。
    """
    return 0
