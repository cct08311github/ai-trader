"""chat_context.py — 組裝 AI 對話的系統上下文（持倉/訊號/損益/風控）.

每次 /api/chat/message 呼叫前調用 build_chat_context(conn)，
回傳完整的系統提示字串，約 1000-1500 tokens。
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Optional

_CAPITAL_JSON = Path(__file__).resolve().parents[4] / "config" / "capital.json"


def _read_nav() -> float:
    """Read total_capital_twd from config/capital.json; fallback to 1_000_000."""
    try:
        data = json.loads(_CAPITAL_JSON.read_text())
        return float(data.get("total_capital_twd", 1_000_000.0))
    except Exception:
        return 1_000_000.0


def build_chat_context(conn) -> str:
    """Query DB and assemble system prompt for the chat LLM.

    Args:
        conn: SQLite connection (read-only). If None, returns minimal context.

    Returns:
        System prompt string with current account state.
    """
    sections: list[str] = []
    sections.append(
        "你是 OpenClaw AI 交易助手。以下是目前帳戶即時狀態（僅供決策參考，不構成交易指令）。\n"
        "請用繁體中文回應。回應保持簡潔，重點在數字與風險評估。"
    )

    if conn is None:
        sections.append("[提示] 資料庫連線不可用，以下資料可能不完整。")
        return "\n\n".join(sections)

    # ── 1. 持倉摘要 ──────────────────────────────────────────────────────────
    try:
        rows = conn.execute(
            """SELECT symbol, quantity, avg_price, current_price, unrealized_pnl
               FROM positions WHERE quantity > 0 ORDER BY symbol"""
        ).fetchall()
        if rows:
            lines = ["[持倉摘要]"]
            total_cost = 0.0
            total_mkt = 0.0
            for r in rows:
                sym = r[0]
                qty = int(r[1] or 0)
                avg = float(r[2] or 0)
                cur = float(r[3] or avg)
                upnl = float(r[4] or 0)
                pct = ((cur - avg) / avg * 100) if avg > 0 else 0
                cost = qty * avg
                mkt = qty * cur
                total_cost += cost
                total_mkt += mkt
                sign = "+" if upnl >= 0 else ""
                lines.append(
                    f"- {sym}：{qty} 股，均價 {avg:.1f}，現價 {cur:.1f}，"
                    f"未實現 {sign}{upnl:.0f} TWD ({sign}{pct:.1f}%)"
                )
            gross_exp_pct = (total_mkt / 500_000 * 100) if total_mkt > 0 else 0
            lines.append(f"  持倉總市值：{total_mkt:,.0f} TWD | gross_exposure≈{gross_exp_pct:.1f}%")
            sections.append("\n".join(lines))
        else:
            sections.append("[持倉摘要]\n目前無持倉。")
    except Exception as e:
        sections.append(f"[持倉摘要]\n查詢失敗：{e}")

    # ── 2. 今日損益 ──────────────────────────────────────────────────────────
    try:
        today_str = datetime.now().strftime("%Y-%m-%d")
        month_str = datetime.now().strftime("%Y-%m")
        from openclaw.pnl_engine import get_today_pnl, get_monthly_pnl
        today_pnl = get_today_pnl(conn, today_str)
        monthly_pnl = get_monthly_pnl(conn, month_str)
        sign_d = "+" if today_pnl >= 0 else ""
        sign_m = "+" if monthly_pnl >= 0 else ""
        sections.append(
            f"[今日損益]\n"
            f"已實現：{sign_d}{today_pnl:.0f} TWD | "
            f"本月累計：{sign_m}{monthly_pnl:.0f} TWD"
        )
    except Exception:
        sections.append("[今日損益]\n查詢失敗（pnl_engine 不可用）。")

    # ── 3. 最近 watcher 訊號 (最新 5 筆) ──────────────────────────────────
    try:
        rows = conn.execute(
            """SELECT agent, model, response, created_at
               FROM llm_traces
               WHERE agent = 'watcher'
               ORDER BY created_at DESC LIMIT 5"""
        ).fetchall()
        if rows:
            lines = ["[最近 watcher 訊號 (最新5筆)]"]
            for r in rows:
                try:
                    resp = json.loads(r[2]) if r[2] else {}
                    ts = datetime.fromtimestamp(r[3]).strftime("%H:%M")
                    sym = resp.get("symbol", "?")
                    sig = resp.get("signal", "?")
                    close = resp.get("close", "-")
                    lines.append(f"- {sym}: signal={sig}, close={close} ({ts} TWN)")
                except Exception:
                    pass
            sections.append("\n".join(lines))
    except Exception:
        pass  # skip if llm_traces unavailable

    # ── 4. 最近成交 (最近 5 筆 fills) ─────────────────────────────────────
    try:
        rows = conn.execute(
            """SELECT symbol, side, qty, price, filled_at
               FROM fills ORDER BY filled_at DESC LIMIT 5"""
        ).fetchall()
        if rows:
            lines = ["[最近成交記錄]"]
            for r in rows:
                sym, side, qty, price, ts = r[0], r[1], r[2], r[3], r[4]
                try:
                    dt = datetime.fromtimestamp(float(ts)).strftime("%m/%d %H:%M")
                except Exception:
                    dt = str(ts)
                lines.append(f"- {side.upper()} {sym} {qty}股 @{price:.1f} ({dt})")
            sections.append("\n".join(lines))
    except Exception:
        pass

    # ── 5. 風控狀態 ───────────────────────────────────────────────────────
    try:
        rows = conn.execute(
            """SELECT symbol, side, qty, price, filled_at
               FROM fills ORDER BY filled_at DESC LIMIT 1"""
        ).fetchall()
        # Rebuild gross_exposure from positions
        pos_rows = conn.execute(
            "SELECT symbol, quantity, avg_price, current_price FROM positions WHERE quantity > 0"
        ).fetchall()
        total_mkt = sum(
            int(r[1]) * float(r[3] or r[2] or 0) for r in pos_rows
        )
        NAV = _read_nav()
        gross_exp = total_mkt / NAV * 100 if NAV > 0 else 0
        sections.append(
            f"[風控狀態]\n"
            f"gross_exposure: {gross_exp:.1f}% | "
            f"每日虧損上限: 5,000 TWD | "
            f"風控模式: {'defensive' if gross_exp > 50 else 'normal'}"
        )
    except Exception:
        pass

    return "\n\n".join(sections)


def parse_proposal_intent(ai_response: str) -> Optional[dict]:
    """Detect if AI response contains a trade proposal intent.

    Returns dict with {action, symbol, qty, price} if detected, else None.
    Very simple keyword scan — good enough for MVP.
    """
    import re
    # Look for patterns like "建議買入 2330 270股 @897" or "buy 2330 270 @897"
    patterns = [
        r"建議(?P<action>買入|賣出)\s*(?P<symbol>\d{4,6})\s*(?P<qty>\d+)\s*股\s*@?\s*(?P<price>[\d.]+)",
        r"(?P<action>buy|sell)\s+(?P<symbol>\d{4,6})\s+(?P<qty>\d+)\s*@\s*(?P<price>[\d.]+)",
    ]
    for pat in patterns:
        m = re.search(pat, ai_response, re.IGNORECASE)
        if m:
            action_raw = m.group("action").lower()
            action = "buy" if action_raw in ("買入", "buy") else "sell"
            return {
                "action": action,
                "symbol": m.group("symbol"),
                "qty": int(m.group("qty")),
                "price": float(m.group("price")),
            }
    return None
