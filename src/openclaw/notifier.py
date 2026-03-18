"""notifier.py — 多管道通知器（Telegram 主 + Email 備援）

解決 Telegram Bot 單點依賴問題（Issue #287）。

優先順序：
    1. Telegram（現有 tg_notify）
    2. Email SMTP（備援）

通知失敗時寫入 incidents 表；flush_pending() 在下次成功時補發。

環境變數：
    # Telegram（沿用原有）
    TELEGRAM_BOT_TOKEN  — Telegram Bot token
    TELEGRAM_CHAT_ID    — 目標 chat id（預設 1017252031）

    # Email 備援
    NOTIFY_EMAIL_TO     — 收件人（逗號分隔多位）
    NOTIFY_EMAIL_FROM   — 寄件人 email
    NOTIFY_EMAIL_SMTP_HOST — SMTP server（預設 smtp.gmail.com）
    NOTIFY_EMAIL_SMTP_PORT — SMTP port（預設 587）
    NOTIFY_EMAIL_USER   — SMTP 認證 username
    NOTIFY_EMAIL_PASS   — SMTP 認證 password

使用方式：
    from openclaw.notifier import notify, flush_pending

    # 一般通知（不需要 DB）
    notify("🚨 風控警報：集中度超標")

    # 附帶 DB 時支援失敗記錄與補發
    notify("🚨 風控警報", conn=conn)
    flush_pending(conn)
"""
from __future__ import annotations

import email.mime.text
import json
import logging
import os
import smtplib
import sqlite3
import uuid
from typing import Optional

from openclaw.tg_notify import send_message as _tg_send

log = logging.getLogger(__name__)

_INCIDENT_SOURCE = "notifier"
_INCIDENT_CODE = "NOTIFY_FAILURE"
_PENDING_CODE = "NOTIFY_PENDING"


# ──────────────────────────────────────────────
# Email fallback
# ──────────────────────────────────────────────

def _send_email(text: str) -> bool:
    """Send a plain-text notification email via SMTP.

    Returns True on success, False on failure (never raises).
    """
    to_raw = os.environ.get("NOTIFY_EMAIL_TO", "").strip()
    if not to_raw:
        log.debug("[notifier] NOTIFY_EMAIL_TO 未設定，跳過 email 備援")
        return False

    from_addr = os.environ.get("NOTIFY_EMAIL_FROM", "").strip()
    smtp_host = os.environ.get("NOTIFY_EMAIL_SMTP_HOST", "smtp.gmail.com").strip()
    smtp_port = int(os.environ.get("NOTIFY_EMAIL_SMTP_PORT", "587"))
    smtp_user = os.environ.get("NOTIFY_EMAIL_USER", "").strip()
    smtp_pass = os.environ.get("NOTIFY_EMAIL_PASS", "").strip()

    if not from_addr or not smtp_user or not smtp_pass:
        log.debug("[notifier] Email 設定不完整，跳過備援")
        return False

    recipients = [addr.strip() for addr in to_raw.split(",") if addr.strip()]

    msg = email.mime.text.MIMEText(text, "plain", "utf-8")
    msg["Subject"] = "[AI-Trader] 通知"
    msg["From"] = from_addr
    msg["To"] = ", ".join(recipients)

    try:
        with smtplib.SMTP(smtp_host, smtp_port, timeout=15) as server:
            server.ehlo()
            server.starttls()
            server.login(smtp_user, smtp_pass)
            server.sendmail(from_addr, recipients, msg.as_string())
        log.info("[notifier] Email 備援通知已發送至 %s", recipients)
        return True
    except Exception as exc:
        log.warning("[notifier] Email 備援通知失敗: %s", exc)
        return False


# ──────────────────────────────────────────────
# Incident persistence
# ──────────────────────────────────────────────

def _record_failure(
    conn: Optional[sqlite3.Connection],
    text: str,
    channels_tried: list[str],
) -> None:
    """Write a NOTIFY_FAILURE incident so flush_pending() can retry later."""
    if conn is None:
        return
    try:
        conn.execute(
            """INSERT INTO incidents
               (incident_id, ts, severity, source, code, detail_json, resolved)
               VALUES (?, datetime('now'), 'warn', ?, ?, ?, 0)""",
            (
                str(uuid.uuid4()),
                _INCIDENT_SOURCE,
                _INCIDENT_CODE,
                json.dumps(
                    {"message": text[:500], "channels_tried": channels_tried},
                    ensure_ascii=True,
                ),
            ),
        )
        conn.commit()
    except Exception as exc:
        log.warning("[notifier] 無法寫入 NOTIFY_FAILURE incident: %s", exc)


def _resolve_incidents(conn: sqlite3.Connection) -> None:
    """Mark all pending NOTIFY_FAILURE incidents as resolved."""
    try:
        conn.execute(
            "UPDATE incidents SET resolved=1 WHERE source=? AND code=? AND resolved=0",
            (_INCIDENT_SOURCE, _INCIDENT_CODE),
        )
        conn.commit()
    except Exception as exc:
        log.warning("[notifier] 無法 resolve incidents: %s", exc)


# ──────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────

def notify(
    text: str,
    conn: Optional[sqlite3.Connection] = None,
) -> bool:
    """Send a notification via Telegram, falling back to Email on failure.

    Args:
        text: Message body (HTML tags accepted for Telegram; plain text for email).
        conn: Optional SQLite connection.  When provided:
              - Failed notifications are recorded in ``incidents``.
              - A subsequent ``flush_pending(conn)`` will retry them.

    Returns:
        True if at least one channel succeeded, False otherwise.
    """
    channels_tried: list[str] = []

    # ── Channel 1: Telegram ──────────────────────────────────────────────
    try:
        tg_ok = _tg_send(text)
    except Exception as exc:
        log.warning("[notifier] Telegram 呼叫異常: %s", exc)
        tg_ok = False

    if tg_ok:
        if conn is not None:
            _resolve_incidents(conn)   # clear any previous failures
        return True

    channels_tried.append("telegram")

    # ── Channel 2: Email SMTP ────────────────────────────────────────────
    email_ok = _send_email(text)
    if email_ok:
        if conn is not None:
            _resolve_incidents(conn)
        return True

    channels_tried.append("email")

    # ── All channels failed ──────────────────────────────────────────────
    log.error("[notifier] 所有通知管道失敗（%s），訊息已記錄 incidents", channels_tried)
    _record_failure(conn, text, channels_tried)
    return False


def flush_pending(conn: sqlite3.Connection) -> int:
    """Retry failed notifications stored in the incidents table.

    Queries unresolved NOTIFY_FAILURE incidents and re-sends each message.
    Successfully sent incidents are marked as resolved.

    Returns:
        Number of incidents successfully re-sent.
    """
    try:
        rows = conn.execute(
            """SELECT incident_id, detail_json
               FROM incidents
               WHERE source=? AND code=? AND resolved=0
               ORDER BY ts ASC""",
            (_INCIDENT_SOURCE, _INCIDENT_CODE),
        ).fetchall()
    except Exception as exc:
        log.warning("[notifier] flush_pending: 無法查詢 incidents: %s", exc)
        return 0

    if not rows:
        return 0

    sent = 0
    for incident_id, detail_json in rows:
        try:
            detail = json.loads(detail_json or "{}")
            msg = detail.get("message", "（訊息遺失）")
        except Exception:
            msg = "（訊息解析失敗）"

        # Prepend a retry note
        retry_msg = f"[補發] {msg}"
        ok = notify(retry_msg)   # does not pass conn to avoid recursive incident writes
        if ok:
            try:
                conn.execute(
                    "UPDATE incidents SET resolved=1 WHERE incident_id=?",
                    (incident_id,),
                )
                conn.commit()
                sent += 1
            except Exception as exc:
                log.warning("[notifier] flush_pending: 無法 resolve %s: %s", incident_id, exc)

    if sent:
        log.info("[notifier] flush_pending: %d/%d 筆補發成功", sent, len(rows))

    return sent
