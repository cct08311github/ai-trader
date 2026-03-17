"""agents/system_health.py — 系統健康監控 Agent。

執行時機：每 30 分鐘（市場時段）/ 每 2 小時（非市場時段）
工作：Python 收集 PM2 / DB / 磁碟資料，Gemini 進行健康評估
"""
from __future__ import annotations
from openclaw.path_utils import get_repo_root

import subprocess
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from openclaw.agents.base import (

    AgentResult, DEFAULT_MODEL, call_agent_llm, open_conn,
    to_agent_result, write_trace,
)

_REPO_ROOT = get_repo_root()

_PROMPT_TEMPLATE = """\
你是 AI Trader 系統的 SystemHealthAgent（系統健康監控員）。

## 當前系統狀態
執行時間：{now_utc}

### PM2 進程狀態
```
{pm2_status}
```

### Watcher 近 5 分鐘是否有活動
近 5 分鐘 watcher traces 數量：{watcher_recent_count}

### 磁碟空間
```
{disk_info}
```

## 任務
根據以上資訊評估系統健康度。
若任何服務 offline 或磁碟使用 > 90%，action_type 改為 "suggest" 並在 proposals 列出修復建議。

## 輸出格式（必須是 JSON）
```json
{{
  "summary": "...",
  "confidence": 0.95,
  "action_type": "observe",
  "proposals": []
}}
```
"""


def _get_pm2_status() -> str:
    try:
        r = subprocess.run(
            ["pm2", "list", "--no-color"],
            capture_output=True, text=True, timeout=10
        )
        return r.stdout[:1000] if r.stdout else "PM2 不可用"
    except Exception as e:
        return f"PM2 查詢失敗：{e}"


def _get_disk_info() -> str:
    try:
        r = subprocess.run(
            ["df", "-h", str(_REPO_ROOT)],
            capture_output=True, text=True, timeout=5
        )
        return r.stdout[:300] if r.stdout else "無法取得磁碟資訊"
    except Exception as e:
        return f"磁碟查詢失敗：{e}"


def _get_watcher_recent_count(conn: sqlite3.Connection) -> int:
    try:
        row = conn.execute(
            "SELECT COUNT(*) FROM llm_traces "
            "WHERE agent='watcher' AND created_at > strftime('%s','now','-5 minutes')"
        ).fetchone()
        return row[0] if row else 0
    except Exception:
        return -1


def run_system_health(
    conn: Optional[sqlite3.Connection] = None,
    db_path: Optional[str] = None,
) -> AgentResult:
    _conn = conn or (open_conn(db_path) if db_path else open_conn())
    try:
        pm2_status = _get_pm2_status()
        disk_info = _get_disk_info()
        watcher_count = _get_watcher_recent_count(_conn)

        prompt = _PROMPT_TEMPLATE.format(
            now_utc=datetime.now(tz=timezone.utc).isoformat(),
            pm2_status=pm2_status,
            disk_info=disk_info,
            watcher_recent_count=watcher_count,
        )

        result_dict = call_agent_llm(prompt, model=DEFAULT_MODEL)
        write_trace(_conn, agent="system_health", prompt=prompt[:500], result=result_dict)
        return to_agent_result(result_dict)
    finally:
        if conn is None:
            _conn.close()
