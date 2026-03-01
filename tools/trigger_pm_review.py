#!/usr/bin/env python3
"""trigger_pm_review.py — 觸發每日 PM 審核（供 cron job / 手動呼叫）

用法：
    python3 tools/trigger_pm_review.py

環境變數：
    AUTH_TOKEN   — API Bearer token（從 .env 讀取）
    AI_TRADER_API — 預設 https://127.0.0.1:8080
"""

import json
import os
import ssl
import sys
import urllib.request
from pathlib import Path

# ── 讀取根目錄 .env（AUTH_TOKEN / GEMINI_API_KEY）──────────────────────────
_ROOT_ENV = Path("/Users/openclaw/.openclaw/.env")
_PROJ_ENV = Path(__file__).parent.parent / "frontend/backend/.env"

def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        k = k.strip()
        if k and k not in os.environ:          # 不覆蓋已存在的變數
            os.environ[k] = v.strip()

_load_dotenv(_ROOT_ENV)
_load_dotenv(_PROJ_ENV)

# ── API 設定 ────────────────────────────────────────────────────────────────
API_BASE   = os.environ.get("AI_TRADER_API", "https://127.0.0.1:8080")
AUTH_TOKEN = os.environ.get("AUTH_TOKEN", "")

# 允許本機自簽憑證（只對 127.0.0.1 使用）
_ssl_ctx = ssl.create_default_context()
_ssl_ctx.check_hostname = False
_ssl_ctx.verify_mode = ssl.CERT_NONE


def call_pm_review() -> dict:
    url = f"{API_BASE}/api/pm/review"
    req = urllib.request.Request(
        url,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {AUTH_TOKEN}",
        },
        data=b"{}",
    )
    with urllib.request.urlopen(req, timeout=120, context=_ssl_ctx) as resp:
        return json.loads(resp.read().decode())


if __name__ == "__main__":
    print(f"[PM Review] 呼叫 {API_BASE}/api/pm/review ...")
    try:
        result = call_pm_review()
        data = result.get("data", {})
        approved = data.get("approved", False)
        reason   = data.get("reason", "")
        source   = data.get("source", "")
        conf     = data.get("confidence", 0)
        status   = "✅ 已授權" if approved else "🚫 已封鎖"
        print(f"[PM Review] {status} | 信心 {conf:.0%} | {reason} ({source})")
        sys.exit(0)
    except Exception as e:
        print(f"[PM Review] 錯誤：{e}", file=sys.stderr)
        sys.exit(1)
