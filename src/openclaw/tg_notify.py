"""tg_notify.py — 輕量 Telegram Bot API 通知工具

使用方式：
    from openclaw.tg_notify import send_message
    send_message("📈 3008 減倉提案已核准")

環境變數：
    TELEGRAM_BOT_TOKEN — required
    TELEGRAM_CHAT_ID   — 預設 1017252031（老闆個人頻道）
"""
from __future__ import annotations

import json
import logging
import os
import urllib.request

log = logging.getLogger(__name__)

_DEFAULT_CHAT_ID = "1017252031"


def send_message_with_buttons(
    text: str,
    buttons: list,
    chat_id: str | None = None,
) -> bool:
    """發送帶 inline keyboard 的 Telegram 訊息。

    Args:
        text:    訊息內容（支援 HTML 格式）
        buttons: list of rows，每 row 為 list of {"text": "...", "callback_data": "..."}
        chat_id: 目標 chat；None 時使用環境變數或預設值

    Returns:
        True = 發送成功；False = 失敗（不拋例外）
    """
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        log.debug("TELEGRAM_BOT_TOKEN 未設定，跳過通知")
        return False

    target = chat_id or os.environ.get("TELEGRAM_CHAT_ID", _DEFAULT_CHAT_ID)
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = json.dumps({
        "chat_id": target,
        "text": text,
        "parse_mode": "HTML",
        "reply_markup": {"inline_keyboard": buttons},
    }).encode()

    try:
        req = urllib.request.Request(
            url, data=payload,
            headers={"Content-Type": "application/json"},
        )
        urllib.request.urlopen(req, timeout=10)
        return True
    except Exception as e:
        log.warning("Telegram inline 通知失敗: %s", e)
        return False


def send_message(text: str, chat_id: str | None = None) -> bool:
    """發送 Telegram 訊息。

    Args:
        text:    訊息內容（支援 HTML 格式）
        chat_id: 目標 chat；None 時使用 TELEGRAM_CHAT_ID 環境變數或預設值

    Returns:
        True = 發送成功；False = 失敗（不拋例外）
    """
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        log.debug("TELEGRAM_BOT_TOKEN 未設定，跳過通知")
        return False

    target = chat_id or os.environ.get("TELEGRAM_CHAT_ID", _DEFAULT_CHAT_ID)
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = json.dumps({
        "chat_id": target,
        "text": text,
        "parse_mode": "HTML",
    }).encode()

    try:
        req = urllib.request.Request(
            url, data=payload,
            headers={"Content-Type": "application/json"},
        )
        urllib.request.urlopen(req, timeout=10)
        return True
    except Exception as e:
        log.warning("Telegram 通知失敗: %s", e)
        return False
