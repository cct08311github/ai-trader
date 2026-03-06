"""proposal_reviewer.py — Gemini 自動審查 pending 策略提案

掃描 strategy_proposals 中 status='pending' 的提案，
呼叫 Gemini 做快速審查，輸出 approve / reject + 理由，
更新 DB 並透過 Telegram 通知。

整合點（ticker_watcher 每輪掃盤後呼叫）：
    from openclaw.proposal_reviewer import auto_review_pending_proposals
    auto_review_pending_proposals(conn)
"""
from __future__ import annotations

import json
import logging
import sqlite3
import time

log = logging.getLogger(__name__)

_MODEL = "gemini-2.0-flash"

_REVIEW_PROMPT_TMPL = """你是一位台股 Portfolio Manager，請快速審查以下減倉提案。

【提案資訊】
標的：{symbol}
目前持倉比重：{weight:.1%}
建議減倉幅度：{reduce_pct:.1%}
觸發原因：{evidence}

【近期持倉概況】
{position_summary}

【審查要求】
- 以風控優先，集中度過高是主要風險
- 回傳嚴格的 JSON，欄位：
  {{
    "decision": "approve" 或 "reject",
    "confidence": 0.0–1.0,
    "reason": "一句話說明理由（繁體中文）"
  }}
- 不要有其他文字，只回傳 JSON
"""


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


def _gemini_review(symbol: str, weight: float, reduce_pct: float,
                   evidence: str, position_summary: str) -> dict:
    """呼叫 Gemini 審查提案，回傳 {decision, confidence, reason}。"""
    import re, os
    from google import genai

    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY 未設定")

    client = genai.Client(api_key=api_key)
    prompt = _REVIEW_PROMPT_TMPL.format(
        symbol=symbol, weight=weight, reduce_pct=reduce_pct,
        evidence=evidence, position_summary=position_summary,
    )
    resp = client.models.generate_content(
        model=_MODEL,
        contents=prompt,
        config=genai.types.GenerateContentConfig(
            response_mime_type="application/json",
        ),
    )
    text = resp.text.strip()

    # 嘗試解析 JSON（容錯 markdown code fence）
    m = re.search(r"\{[\s\S]*\}", text)
    if m:
        return json.loads(m.group(0))
    return json.loads(text)


def auto_review_pending_proposals(conn: sqlite3.Connection) -> int:
    """審查所有 pending proposals，核准/拒絕並傳送 Telegram 通知。

    Returns:
        審查完成的 proposal 數量
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
    reviewed = 0

    for proposal_id, generated_by, target_rule, evidence, proposal_json_str in rows:
        try:
            proposal = json.loads(proposal_json_str or "{}")
            symbol = proposal.get("symbol", "?")
            reduce_pct = float(proposal.get("reduce_pct", 0))
            weight = float(proposal.get("current_weight",
                           proposal.get("weight", 0)))

            result = _gemini_review(
                symbol=symbol, weight=weight, reduce_pct=reduce_pct,
                evidence=evidence or "", position_summary=position_summary,
            )

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
            sym_display = _fmt_symbol(conn, symbol)
            icon = "✅" if new_status == "approved" else "🚫"
            msg = (
                f"{icon} <b>[盤中策略審查]</b>\n"
                f"標的：<b>{sym_display}</b> | 規則：{target_rule}\n"
                f"決定：<b>{'核准減倉' if new_status == 'approved' else '拒絕'}</b>"
                f"（信心 {confidence:.0%}）\n"
                f"建議減倉：{reduce_pct:.1%}　目前比重：{weight:.1%}\n"
                f"理由：{reason}"
            )
            send_message(msg)
            log.info("[proposal_reviewer] %s → %s (conf=%.2f) %s",
                     proposal_id[:8], new_status, confidence, reason)
            reviewed += 1

        except Exception as e:
            log.warning("[proposal_reviewer] proposal %s 審查失敗: %s", proposal_id[:8], e)

    return reviewed
