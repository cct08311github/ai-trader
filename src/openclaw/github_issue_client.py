"""github_issue_client.py — AI Trader GitHub Issue 自動開設客戶端 [Issue #196]

供策略小組 Agent 在產出重大提案時自動建立 GitHub Issue，
確保每個策略決策都有可追蹤的 GitHub 記錄。

環境變數（從 frontend/backend/.env 或系統環境讀取）：
  GITHUB_TOKEN  — Personal Access Token（需 repo issues 讀寫權限）
  GITHUB_OWNER  — 倉庫擁有者（預設 cct08311github）
  GITHUB_REPO   — 倉庫名稱（預設 ai-trader）

使用方式：
  from openclaw.github_issue_client import open_strategy_proposal_issue
  url = open_strategy_proposal_issue(proposal_data, committee_context)
"""
from __future__ import annotations

import json
import logging
import os
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta
from typing import Any

log = logging.getLogger(__name__)

_TZ_TWN = timezone(timedelta(hours=8))

_GITHUB_API = "https://api.github.com"
_DEFAULT_OWNER = "cct08311github"
_DEFAULT_REPO  = "ai-trader"

# 標籤定義：(name, color_hex, description)
_REQUIRED_LABELS: list[tuple[str, str, str]] = [
    ("strategy-proposal", "0075ca", "AI 策略小組自動產出的策略建議"),
    ("discussion",        "e4e669", "市場討論與分析摘要"),
    ("P0",                "d73a4a", "緊急：需立即處理"),
]


def _token() -> str:
    return os.environ.get("GITHUB_TOKEN", "")


def _owner() -> str:
    return os.environ.get("GITHUB_OWNER", _DEFAULT_OWNER)


def _repo() -> str:
    return os.environ.get("GITHUB_REPO", _DEFAULT_REPO)


def _request(method: str, path: str, body: dict | None = None) -> dict[str, Any]:
    """執行 GitHub API 請求，回傳解析後的 JSON。"""
    token = _token()
    if not token:
        raise ValueError("GITHUB_TOKEN 未設定，無法呼叫 GitHub API")

    url = f"{_GITHUB_API}{path}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        url,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "Content-Type": "application/json",
            "User-Agent": "ai-trader-bot/1.0",
        },
        data=data,
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        body_text = exc.read().decode(errors="replace")
        raise RuntimeError(f"GitHub API {method} {url} 失敗 ({exc.code}): {body_text}") from exc


# ── 標籤管理 ─────────────────────────────────────────────────────────────────

def ensure_labels() -> list[str]:
    """確保必要 labels 存在於 repo（冪等，已存在則跳過）。
    回傳已建立或已存在的 label 名稱清單。
    """
    path = f"/repos/{_owner()}/{_repo()}/labels"
    try:
        existing = {lbl["name"] for lbl in _request("GET", path)}
    except Exception as exc:
        log.warning("無法取得現有 labels: %s", exc)
        existing = set()

    created: list[str] = []
    for name, color, description in _REQUIRED_LABELS:
        if name in existing:
            log.debug("label 已存在: %s", name)
            created.append(name)
            continue
        try:
            _request("POST", path, {"name": name, "color": color, "description": description})
            log.info("已建立 label: %s", name)
            created.append(name)
        except Exception as exc:
            log.warning("建立 label %s 失敗: %s", name, exc)

    return created


# ── Issue 建立 ────────────────────────────────────────────────────────────────

def _fmt_pct(v: float | None) -> str:
    if v is None:
        return "N/A"
    return f"{v:+.1f}%"


def _build_strategy_body(
    proposal: dict[str, Any],
    committee: dict[str, Any],
    proposal_id: str | None,
) -> str:
    now = datetime.now(_TZ_TWN).strftime("%Y-%m-%d %H:%M")
    bull   = committee.get("bull", {})
    bear   = committee.get("bear", {})
    arb    = committee.get("arbiter", {})
    market = committee.get("market_data", {})

    confidence  = proposal.get("confidence", 0)
    target_rule = proposal.get("target_rule", "")
    proposed    = proposal.get("proposed_value", "")
    evidence    = proposal.get("supporting_evidence", "")
    stance      = arb.get("stance", "neutral")

    lines = [
        f"## 市場摘要",
        "",
        f"{market}" if isinstance(market, str) else json.dumps(market, ensure_ascii=False, indent=2),
        "",
        "## 多空辯論",
        "",
        f"**看多論點 (Bull)**  (置信 {_fmt_pct(bull.get('confidence', 0) * 100)})",
        f"{bull.get('thesis', '—')}",
        "",
        f"**看空風險 (Bear)**  (置信 {_fmt_pct(bear.get('confidence', 0) * 100)})",
        f"{bear.get('thesis', '—')}",
        "",
        f"**仲裁結論 (Arbiter)**  — 立場：`{stance}`",
        f"{arb.get('summary', '—')}",
        "",
        "## 建議行動",
        "",
        f"- 目標規則：`{target_rule}`",
        f"- 建議值：`{proposed}`",
        f"- 支撐證據：{evidence}",
        f"- 置信水準：{confidence:.0%}",
        "",
        "## 追蹤",
        "",
        f"- 提案 ID（DB）：`{proposal_id or '—'}`",
        f"- 產出時間：{now}",
        f"- 來源：strategy_committee（自動）",
        "",
        "_此 Issue 由 AI Trader 策略小組自動產出，需人工確認後才會執行。_",
    ]
    return "\n".join(lines)


def open_strategy_proposal_issue(
    proposal: dict[str, Any],
    committee_context: dict[str, Any],
    proposal_id: str | None = None,
) -> str | None:
    """為策略小組提案建立 GitHub Issue。

    Args:
        proposal: 提案 dict（含 target_rule, proposed_value, supporting_evidence, confidence）
        committee_context: 含 bull/bear/arbiter/market_data 的 dict
        proposal_id: SQLite 中的 proposal_id（用於追蹤）

    Returns:
        建立的 Issue URL，失敗時回傳 None（不拋例外，避免中斷主流程）
    """
    if not _token():
        log.warning("GITHUB_TOKEN 未設定，跳過 GitHub Issue 建立")
        return None

    arb    = committee_context.get("arbiter", {})
    stance = arb.get("stance", "neutral")
    conf   = proposal.get("confidence", 0)
    rule   = proposal.get("target_rule", "策略建議")

    # 標題格式：[策略] {立場} — {規則} (置信 XX%)
    stance_label = {"bull": "做多", "bear": "做空", "neutral": "觀望"}.get(stance, stance)
    title = f"[策略] {stance_label} — {rule} (置信 {conf:.0%})"

    labels = ["strategy-proposal"]
    if stance == "bear":
        labels.append("discussion")
    # 按置信度決定優先級 label
    if conf >= 0.75:
        labels.append("P1")
    elif conf >= 0.5:
        labels.append("P2")
    else:
        labels.append("P3")

    body = _build_strategy_body(proposal, committee_context, proposal_id)

    try:
        result = _request(
            "POST",
            f"/repos/{_owner()}/{_repo()}/issues",
            {"title": title, "body": body, "labels": labels},
        )
        url = result.get("html_url", "")
        issue_num = result.get("number")
        log.info("已建立 GitHub Issue #%s: %s", issue_num, url)
        return url
    except Exception as exc:
        log.error("建立 GitHub Issue 失敗（非致命）: %s", exc)
        return None


def open_bear_dissent_issue(
    bear_thesis: str,
    market_data: Any,
    confidence: float,
    proposal_id: str | None = None,
) -> str | None:
    """當 Bear 置信度高（>= 0.7）且與多數方向相反時，建立異見記錄 Issue。"""
    if not _token():
        log.warning("GITHUB_TOKEN 未設定，跳過異見 Issue 建立")
        return None

    now = datetime.now(_TZ_TWN).strftime("%Y-%m-%d %H:%M")
    title = f"[異見] Bear 高置信警告 (置信 {confidence:.0%}) — {now}"

    body_lines = [
        "## 異見摘要",
        "",
        bear_thesis,
        "",
        "## 市場背景",
        "",
        f"{market_data}" if isinstance(market_data, str) else json.dumps(market_data, ensure_ascii=False, indent=2),
        "",
        "## 追蹤",
        "",
        f"- 提案 ID（DB）：`{proposal_id or '—'}`",
        f"- 置信度：{confidence:.0%}",
        f"- 產出時間：{now}",
        "",
        "_此 Issue 由 AI Trader Bear Analyst 自動產出，需人工確認是否調整部位。_",
    ]

    try:
        result = _request(
            "POST",
            f"/repos/{_owner()}/{_repo()}/issues",
            {
                "title": title,
                "body": "\n".join(body_lines),
                "labels": ["strategy-proposal", "discussion", "P2"],
            },
        )
        url = result.get("html_url", "")
        log.info("已建立異見 Issue: %s", url)
        return url
    except Exception as exc:
        log.error("建立異見 Issue 失敗（非致命）: %s", exc)
        return None
