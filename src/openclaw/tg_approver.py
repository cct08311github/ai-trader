"""tg_approver.py — Telegram 策略提案通知與 inline 核准

功能：
    - notify_pending_proposals(conn)  : 掃描 pending 提案，發 Telegram inline 按鈕
    - poll_approval_callbacks(conn)   : 處理 ✅/🚫 按鈕按下，更新 DB 狀態

狀態持久化：
    working_memory 表，scope='tg_approver'
      key='notified_ids'   → JSON 陣列，已發通知的 proposal_id
      key='update_offset'  → int，Telegram getUpdates offset
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
        """SELECT proposal_id, target_rule, proposed_value, confidence
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

        # 解析 proposed_value
        try:
            pv = json.loads(row["proposed_value"])
        except Exception:
            pv = {}

        symbol   = pv.get("symbol", "")
        action   = pv.get("action", "")
        qty      = pv.get("quantity", "")
        price    = pv.get("target_price", "")

        sym_display = _fmt_symbol(conn, symbol) if symbol else ""

        emoji = "🔄" if rule == "POSITION_REBALANCE" else "🎯"
        lines = [f"{emoji} <b>策略提案審查</b>", f"類型：{rule}"]
        if sym_display:
            lines.append(f"標的：{sym_display}")
        if action:
            lines.append(f"動作：{action}")
        if qty:
            lines.append(f"數量：{qty} 股")
        if price:
            lines.append(f"目標價：{price}")
        lines.append(f"信心度：{conf:.0%}")
        lines.append(f"\n<i>ID：{pid[:8]}…</i>")

        buttons = [[
            {"text": "✅ 核准", "callback_data": f"approve:{pid}"},
            {"text": "🚫 拒絕", "callback_data": f"reject:{pid}"},
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
    """Poll Telegram getUpdates，處理 ✅/🚫 callback_query，更新提案狀態。

    Returns:
        處理的 callback 數量
    """
    from openclaw.tg_notify import send_message  # lazy import

    tok = _token()
    if not tok:
        return 0

    offset = int(_wm_get(conn, "update_offset") or 0)
    url = (
        f"https://api.telegram.org/bot{tok}/getUpdates"
        f"?offset={offset}&limit=10&timeout=1"
        f'&allowed_updates=["callback_query"]'
    )

    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read())
    except Exception as e:
        log.debug("Telegram getUpdates error: %s", e)
        return 0

    if not data.get("ok"):
        log.warning("getUpdates not ok: %s", data)
        return 0

    updates = data.get("result", [])
    processed = 0
    new_offset = offset

    for upd in updates:
        uid = upd["update_id"]
        new_offset = uid + 1
        cb = upd.get("callback_query")
        if not cb:
            continue

        cb_id = cb["id"]
        cb_data = cb.get("data", "")

        if ":" not in cb_data:
            _answer_callback(tok, cb_id, "無效指令")
            continue

        action, proposal_id = cb_data.split(":", 1)
        if action == "approve":
            new_status, reply = "approved", "✅ 已核准"
        elif action == "reject":
            new_status, reply = "rejected", "🚫 已拒絕"
        else:
            _answer_callback(tok, cb_id, "未知指令")
            continue

        cur = conn.execute(
            "SELECT proposal_id, target_rule, proposed_value"
            " FROM strategy_proposals WHERE proposal_id=?",
            (proposal_id,),
        ).fetchone()

        if not cur:
            _answer_callback(tok, cb_id, "找不到提案")
            continue

        conn.execute(
            "UPDATE strategy_proposals SET status=? WHERE proposal_id=?",
            (new_status, proposal_id),
        )
        conn.commit()

        rule = cur["target_rule"]
        try:
            pv = json.loads(cur["proposed_value"])
            symbol = pv.get("symbol", "")
            sym_display = _fmt_symbol(conn, symbol) if symbol else ""
        except Exception:
            sym_display = ""

        confirm = f"{reply} — {rule}"
        if sym_display:
            confirm += f"（{sym_display}）"
        send_message(confirm)

        _answer_callback(tok, cb_id, reply)
        log.info("[tg_approver] %s proposal %s (%s)", new_status, proposal_id[:8], rule)
        processed += 1

    if new_offset > offset:
        _wm_set(conn, "update_offset", new_offset)

    return processed
