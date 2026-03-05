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
