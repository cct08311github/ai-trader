"""tests/test_tg_kill_switch.py — Telegram Kill Switch 單元測試"""
from __future__ import annotations

import json
import threading
from pathlib import Path
from unittest.mock import MagicMock, patch


# ── helpers ──────────────────────────────────────────────────────────────────

def _make_update(update_id: int, chat_id: str, text: str) -> dict:
    return {
        "update_id": update_id,
        "message": {
            "message_id": 1,
            "from": {"id": int(chat_id), "first_name": "Test"},
            "chat": {"id": int(chat_id)},
            "text": text,
        },
    }


def _ok_result(updates: list) -> dict:
    return {"ok": True, "result": updates}


def _empty_result() -> dict:
    return {"ok": True, "result": []}


# ── test_emergency_stop_creates_file ─────────────────────────────────────────

def test_emergency_stop_creates_file(tmp_path, monkeypatch):
    """
    /emergency_stop 指令應建立 .EMERGENCY_STOP 檔案並回覆確認訊息。
    """
    import openclaw.tg_kill_switch as ks

    stop_path = tmp_path / ".EMERGENCY_STOP"
    monkeypatch.setattr(ks, "_get_emergency_stop_path", lambda: stop_path)

    sent_messages = []

    def fake_send(token, chat_id, text):
        sent_messages.append(text)

    monkeypatch.setattr(ks, "_send_reply", fake_send)

    # Reset module-level stop event
    ks._stop_event = threading.Event()

    ks._handle_command("/emergency_stop", "1017252031", "test-token")

    assert stop_path.exists(), ".EMERGENCY_STOP 應已建立"
    assert any("緊急停止" in m for m in sent_messages), "應回覆緊急停止確認訊息"
    assert ks._stop_event.is_set(), "stop_event 應被設定"


# ── test_unauthorized_message_ignored ────────────────────────────────────────

def test_unauthorized_message_ignored(tmp_path, monkeypatch):
    """
    非授權 chat_id 的訊息應被忽略，不執行任何指令。
    """
    import openclaw.tg_kill_switch as ks

    stop_path = tmp_path / ".EMERGENCY_STOP"
    monkeypatch.setattr(ks, "_get_emergency_stop_path", lambda: stop_path)

    sent_messages = []
    monkeypatch.setattr(ks, "_send_reply", lambda t, c, m: sent_messages.append(m))

    # 模擬兩個 updates：一個授權、一個未授權
    authorized_id = "1017252031"
    unauthorized_id = "9999999"

    # Polling 在收到第二個 empty result 後停止
    call_count = [0]
    stop_event = threading.Event()

    responses = [
        _ok_result([
            _make_update(1, unauthorized_id, "/emergency_stop"),
        ]),
        _empty_result(),  # 第二次呼叫後 stop
    ]

    def fake_tg_request(token, method, params):
        if method == "getUpdates":
            idx = call_count[0]
            call_count[0] += 1
            if call_count[0] >= len(responses):
                stop_event.set()
            return responses[idx] if idx < len(responses) else _empty_result()
        return {"ok": True}

    monkeypatch.setattr(ks, "_tg_request", fake_tg_request)

    # 執行 poll_loop 一個 tick（直接測試邏輯，不啟動執行緒）
    # 直接呼叫 _poll_loop 但透過 stop_event 在第一輪後停止
    single_stop = threading.Event()

    fake_responses = iter([
        _ok_result([_make_update(1, unauthorized_id, "/emergency_stop")]),
    ])

    def fake_tg2(token, method, params):
        if method == "getUpdates":
            try:
                result = next(fake_responses)
                single_stop.set()  # 下次迴圈會停止
                return result
            except StopIteration:
                return _empty_result()
        return {"ok": True}

    monkeypatch.setattr(ks, "_tg_request", fake_tg2)

    # 跑一次 poll_loop iteration 邏輯：直接呼叫 _handle_command 並確認結果
    # （不測執行緒邏輯，只驗 chat_id 授權過濾在 _poll_loop 中正確）
    # 改為直接驗證：未授權者呼叫 _handle_command 仍會執行（因為 _poll_loop 負責過濾）
    # 所以這裡測 _poll_loop 的過濾邏輯

    handled_commands = []
    original_handle = ks._handle_command

    def tracking_handle(command, chat_id, token):
        handled_commands.append((command, chat_id))
        original_handle(command, chat_id, token)

    monkeypatch.setattr(ks, "_handle_command", tracking_handle)

    final_stop = threading.Event()
    responses2 = [
        _ok_result([_make_update(1, unauthorized_id, "/emergency_stop")]),
        _ok_result([]),  # 第二次 polling 空結果，讓 loop 繼續直到 stop
    ]
    call_idx = [0]

    def fake_tg3(token, method, params):
        if method == "getUpdates":
            i = call_idx[0]
            call_idx[0] += 1
            if i == 0:
                return responses2[0]
            # 第二次設定 stop 並回空
            final_stop.set()
            return _empty_result()
        return {"ok": True}

    monkeypatch.setattr(ks, "_tg_request", fake_tg3)

    t = threading.Thread(
        target=ks._poll_loop,
        args=("test-token", authorized_id, final_stop),
        daemon=True,
    )
    t.start()
    t.join(timeout=3)

    # 未授權的 chat_id 訊息不應觸發任何指令
    assert not stop_path.exists(), "未授權訊息不應建立 .EMERGENCY_STOP"
    assert len(handled_commands) == 0, "未授權訊息不應呼叫 _handle_command"


# ── test_trading_status_reply ─────────────────────────────────────────────────

def test_trading_status_reply(tmp_path, monkeypatch):
    """
    /trading_status 應回報 trading_enabled 與 simulation_mode 狀態。
    """
    import openclaw.tg_kill_switch as ks

    stop_path = tmp_path / ".EMERGENCY_STOP"
    monkeypatch.setattr(ks, "_get_emergency_stop_path", lambda: stop_path)

    state = {"trading_enabled": True, "simulation_mode": False}
    monkeypatch.setattr(ks, "_get_system_state", lambda: state)

    sent_messages = []
    monkeypatch.setattr(ks, "_send_reply", lambda t, c, m: sent_messages.append(m))

    ks._handle_command("/trading_status", "1017252031", "test-token")

    assert len(sent_messages) == 1
    reply = sent_messages[0]
    assert "trading_enabled" in reply
    assert "True" in reply      # trading_enabled=True
    assert "實盤" in reply       # simulation_mode=False


def test_trading_status_shows_simulation_mode(tmp_path, monkeypatch):
    """
    simulation_mode=True 時應顯示「模擬盤」。
    """
    import openclaw.tg_kill_switch as ks

    stop_path = tmp_path / ".EMERGENCY_STOP"
    monkeypatch.setattr(ks, "_get_emergency_stop_path", lambda: stop_path)

    state = {"trading_enabled": False, "simulation_mode": True}
    monkeypatch.setattr(ks, "_get_system_state", lambda: state)

    sent_messages = []
    monkeypatch.setattr(ks, "_send_reply", lambda t, c, m: sent_messages.append(m))

    ks._handle_command("/trading_status", "1017252031", "test-token")

    assert "模擬盤" in sent_messages[0]


def test_trading_status_shows_emergency_stop_active(tmp_path, monkeypatch):
    """
    .EMERGENCY_STOP 存在時，/trading_status 應標示已觸發緊急停止。
    """
    import openclaw.tg_kill_switch as ks

    stop_path = tmp_path / ".EMERGENCY_STOP"
    stop_path.touch()  # 預先建立
    monkeypatch.setattr(ks, "_get_emergency_stop_path", lambda: stop_path)
    monkeypatch.setattr(ks, "_get_system_state", lambda: {"trading_enabled": False, "simulation_mode": True})

    sent_messages = []
    monkeypatch.setattr(ks, "_send_reply", lambda t, c, m: sent_messages.append(m))

    ks._handle_command("/trading_status", "1017252031", "test-token")

    assert "緊急停止" in sent_messages[0]
    assert "True" in sent_messages[0]  # .EMERGENCY_STOP 存在 = True


# ── test_kill_switch_skips_if_no_token ───────────────────────────────────────

def test_kill_switch_skips_if_no_token(monkeypatch):
    """
    TELEGRAM_BOT_TOKEN 未設定時，start_kill_switch_listener 應回傳 None，不啟動執行緒。
    """
    import openclaw.tg_kill_switch as ks

    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)

    result = ks.start_kill_switch_listener()

    assert result is None, "未設定 token 時應回傳 None"


def test_kill_switch_starts_thread_when_token_set(monkeypatch):
    """
    TELEGRAM_BOT_TOKEN 有設定時，start_kill_switch_listener 應回傳已啟動的 daemon thread。
    """
    import openclaw.tg_kill_switch as ks

    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-bot-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "1017252031")

    # Mock _tg_request 以避免真實 API 呼叫
    def fake_tg_request(token, method, params):
        # 直接設定 stop event 讓執行緒退出
        if ks._stop_event:
            ks._stop_event.set()
        return {"ok": True, "result": []}

    monkeypatch.setattr(ks, "_tg_request", fake_tg_request)

    thread = ks.start_kill_switch_listener()

    try:
        assert thread is not None, "有設定 token 時應回傳執行緒"
        assert thread.daemon, "執行緒應為 daemon"
        assert thread.name == "tg-kill-switch"
        thread.join(timeout=3)
    finally:
        ks.stop_kill_switch_listener()


# ── test_unknown_command_reply ────────────────────────────────────────────────

def test_unknown_command_reply(tmp_path, monkeypatch):
    """
    未知指令應回覆可用指令清單。
    """
    import openclaw.tg_kill_switch as ks

    monkeypatch.setattr(ks, "_get_emergency_stop_path", lambda: tmp_path / ".EMERGENCY_STOP")

    sent_messages = []
    monkeypatch.setattr(ks, "_send_reply", lambda t, c, m: sent_messages.append(m))

    ks._handle_command("/unknown_cmd", "1017252031", "test-token")

    assert len(sent_messages) == 1
    assert "/emergency_stop" in sent_messages[0]
    assert "/trading_status" in sent_messages[0]


# ── test_command_with_bot_name_suffix ────────────────────────────────────────

def test_command_with_bot_name_suffix(tmp_path, monkeypatch):
    """
    /emergency_stop@MyBot 格式的指令應正確解析（去除 @bot_name 後綴）。
    """
    import openclaw.tg_kill_switch as ks

    stop_path = tmp_path / ".EMERGENCY_STOP"
    monkeypatch.setattr(ks, "_get_emergency_stop_path", lambda: stop_path)

    sent_messages = []
    monkeypatch.setattr(ks, "_send_reply", lambda t, c, m: sent_messages.append(m))

    ks._stop_event = threading.Event()

    ks._handle_command("/emergency_stop@MyTradingBot", "1017252031", "test-token")

    assert stop_path.exists(), "@bot_name 後綴不應影響指令解析"
