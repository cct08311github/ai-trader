"""tg_kill_switch.py — Telegram 遠端 Kill Switch

透過 Telegram Bot Polling 接收操作員指令：
  /emergency_stop — 建立 .EMERGENCY_STOP，停止 watcher
  /trading_status — 回報當前交易狀態

只接受 TELEGRAM_CHAT_ID 的訊息（防止未授權操作）。

環境變數：
    TELEGRAM_BOT_TOKEN — 必填（未設定則不啟動）
    TELEGRAM_CHAT_ID   — 授權的 chat ID（預設 1017252031）
"""
from __future__ import annotations

import json
import logging
import os
import threading
import urllib.request
from pathlib import Path
from typing import Optional

from openclaw.path_utils import get_repo_root

log = logging.getLogger(__name__)

_DEFAULT_CHAT_ID = "1017252031"
_POLL_TIMEOUT = 30  # long-poll timeout (seconds)
_EMERGENCY_STOP_FILENAME = ".EMERGENCY_STOP"

# Module-level stop event — set to stop the polling thread gracefully
_stop_event: Optional[threading.Event] = None


def _get_emergency_stop_path() -> Path:
    """返回 .EMERGENCY_STOP 的絕對路徑（repo root）。"""
    return get_repo_root() / _EMERGENCY_STOP_FILENAME


def _get_system_state() -> dict:
    """讀取 config/system_state.json，失敗時回傳預設值。"""
    from openclaw.config_manager import get_config
    return get_config().system_state()


def _tg_request(token: str, method: str, params: dict) -> Optional[dict]:
    """呼叫 Telegram Bot API，回傳 JSON 結果；失敗時回傳 None。"""
    url = f"https://api.telegram.org/bot{token}/{method}"
    payload = json.dumps(params).encode()
    try:
        req = urllib.request.Request(
            url, data=payload,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=_POLL_TIMEOUT + 5) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:  # noqa: BLE001
        log.debug("tg_kill_switch: API 呼叫失敗 %s: %s", method, e)
        return None


def _send_reply(token: str, chat_id: str, text: str) -> None:
    """發送 Telegram 文字訊息。"""
    _tg_request(token, "sendMessage", {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
    })


def _handle_command(command: str, chat_id: str, token: str) -> None:
    """處理 /emergency_stop 或 /trading_status 指令。"""
    cmd = command.strip().lower().split("@")[0]  # 去除 @bot_name 後綴

    if cmd == "/emergency_stop":
        stop_path = _get_emergency_stop_path()
        try:
            stop_path.touch(exist_ok=True)
            log.warning("[kill_switch] EMERGENCY STOP triggered via Telegram. File: %s", stop_path)
            _send_reply(token, chat_id,
                        "🚨 <b>緊急停止已觸發</b>\n"
                        f".EMERGENCY_STOP 已建立於 {stop_path}\n"
                        "Watcher 將在下一個掃盤週期結束後停止自動交易。")
        except OSError as e:
            log.error("[kill_switch] 無法建立 .EMERGENCY_STOP: %s", e)
            _send_reply(token, chat_id, f"❌ 建立 .EMERGENCY_STOP 失敗: {e}")
        # 設定 stop event 讓 polling 執行緒退出
        if _stop_event is not None:
            _stop_event.set()

    elif cmd == "/trading_status":
        state = _get_system_state()
        stop_exists = _get_emergency_stop_path().exists()

        trading_enabled = state.get("trading_enabled", False)
        simulation_mode = state.get("simulation_mode", True)
        mode_str = "模擬盤" if simulation_mode else "實盤"

        if stop_exists:
            status_icon = "🛑"
            status_text = "已觸發緊急停止"
        elif trading_enabled:
            status_icon = "✅"
            status_text = "交易中"
        else:
            status_icon = "⏸️"
            status_text = "暫停"

        msg = (
            f"{status_icon} <b>交易系統狀態</b>\n"
            f"狀態：{status_text}\n"
            f"模式：{mode_str}\n"
            f"trading_enabled：{trading_enabled}\n"
            f".EMERGENCY_STOP 存在：{stop_exists}"
        )
        _send_reply(token, chat_id, msg)

    else:
        _send_reply(token, chat_id,
                    "可用指令：\n/emergency_stop — 緊急停止交易\n/trading_status — 查詢系統狀態")


def _poll_loop(token: str, authorized_chat_id: str, stop_event: threading.Event) -> None:
    """Telegram long-polling 主迴圈，在 daemon thread 中執行。"""
    offset = 0
    log.info("[kill_switch] Telegram Kill Switch 開始監聽 (chat_id=%s)", authorized_chat_id)

    while not stop_event.is_set():
        result = _tg_request(token, "getUpdates", {
            "offset": offset,
            "timeout": _POLL_TIMEOUT,
            "allowed_updates": ["message"],
        })

        if result is None or not result.get("ok"):
            # 網路暫時失敗，等一下再試
            stop_event.wait(timeout=5)
            continue

        for update in result.get("result", []):
            offset = update["update_id"] + 1
            msg = update.get("message", {})
            if not msg:
                continue

            sender_id = str(msg.get("from", {}).get("id", ""))
            text = msg.get("text", "").strip()

            # 授權檢查：只接受 TELEGRAM_CHAT_ID 的訊息
            if sender_id != authorized_chat_id:
                log.warning(
                    "[kill_switch] 拒絕未授權訊息 from chat_id=%s (text=%r)",
                    sender_id, text[:50],
                )
                continue

            if text.startswith("/"):
                log.info("[kill_switch] 收到指令: %r from %s", text, sender_id)
                _handle_command(text, authorized_chat_id, token)

    log.info("[kill_switch] Telegram Kill Switch 執行緒結束")


def start_kill_switch_listener() -> Optional[threading.Thread]:
    """啟動 Telegram Kill Switch 背景監聽執行緒。

    若 TELEGRAM_BOT_TOKEN 未設定，則靜默跳過（不拋例外）。

    Returns:
        threading.Thread — 已啟動的背景執行緒；未設定 token 時回傳 None。
    """
    global _stop_event

    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        log.debug("[kill_switch] TELEGRAM_BOT_TOKEN 未設定，跳過 Kill Switch 監聽")
        return None

    authorized_chat_id = os.environ.get("TELEGRAM_CHAT_ID", _DEFAULT_CHAT_ID).strip()

    _stop_event = threading.Event()
    thread = threading.Thread(
        target=_poll_loop,
        args=(token, authorized_chat_id, _stop_event),
        name="tg-kill-switch",
        daemon=True,  # 主程式結束時自動清理
    )
    thread.start()
    log.info("[kill_switch] Kill Switch 監聽執行緒已啟動 (authorized_chat_id=%s)", authorized_chat_id)
    return thread


def stop_kill_switch_listener() -> None:
    """停止 Kill Switch 監聽（供測試或明確關閉使用）。"""
    global _stop_event
    if _stop_event is not None:
        _stop_event.set()
