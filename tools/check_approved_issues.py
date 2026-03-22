#!/usr/bin/env python3
# tools/check_approved_issues.py
"""check_approved_issues.py — Coder Agent 自動化腳本 [Phase 6]

掃描 GitHub Issues 中標記 `approved` label 的 issue，
針對每個 approved issue：
1. 解析 issue 中的策略參數（SignalParams）
2. 呼叫 backtest engine 執行回測
3. 計算 Sharpe、MaxDrawdown、ROI 等指標
4. 將結果回寫到 GitHub Issue comment

用法：
    PYTHONPATH=src python tools/check_approved_issues.py [--dry-run] [--db PATH]

環境變數：
    GITHUB_TOKEN        GitHub Personal Access Token
    GITHUB_REPO         owner/repo（預設 cct08311github/ai-trader）
    AI_TRADER_DB_PATH   SQLite 路徑（預設 data/sqlite/trades.db）
    BACKTEST_DAYS       回測天數（預設 180）
    BACKTEST_CAPITAL    初始資金（預設 1000000）

回傳碼：
    0 = 成功（含 0 approved issues）
    1 = 錯誤（GitHub API 失敗、DB 不存在等）
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from dataclasses import asdict
from datetime import datetime, timezone, timedelta
from pathlib import Path

# ── 路徑設定（支援 PYTHONPATH=src 與 installed package 兩種情境）──────────
_PROJECT = Path(__file__).resolve().parents[1]
_DEFAULT_DB = _PROJECT / "data" / "sqlite" / "trades.db"

# ── 環境變數 ────────────────────────────────────────────────────────────────
_GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
_GITHUB_REPO  = os.environ.get("GITHUB_REPO", "cct08311github/ai-trader")
_DB_PATH      = os.environ.get("AI_TRADER_DB_PATH", str(_DEFAULT_DB))
_BACKTEST_DAYS    = int(os.environ.get("BACKTEST_DAYS", "180"))
_BACKTEST_CAPITAL = float(os.environ.get("BACKTEST_CAPITAL", "1_000_000"))

_GITHUB_API = "https://api.github.com"
_APPROVED_LABEL = "approved"
_IN_PROGRESS_LABEL = "in-progress"
_NEEDS_VERIFICATION_LABEL = "needs-verification"
_RESULTS_STATE_FILE = _PROJECT / "config" / "coder_agent_results.json"
_VERIFICATION_WINDOW_DAYS = int(os.environ.get("VERIFICATION_WINDOW_DAYS", "30"))
_VERIFICATION_KEYWORDS = {
    "before_after": (
        "before/after",
        "before",
        "after",
        "前",
        "後",
    ),
    "time_window": (
        "verification window",
        "time window",
        "date range",
        "驗證時間",
        "時間範圍",
        "期間",
    ),
    "regression": (
        "regression test",
        "regression",
        "回歸測試",
        "pytest",
        "vitest",
        "test",
    ),
}

# ── Coder Agent Prompt Template ──────────────────────────────────────────────
CODER_AGENT_PROMPT = """
You are the Coder Agent for AI Trader system.

Issue #{issue_number}: {issue_title}

Issue Body:
{issue_body}

Your task:
1. Parse any strategy parameter changes described in the issue
2. Run backtest validation using the existing backtest engine
3. Report metrics: Sharpe Ratio, Max Drawdown %, ROI %, Win Rate, Total Trades
4. Decide if the strategy change should be approved based on:
   - Sharpe > 0.5 (minimum viable)
   - Max Drawdown < 20%
   - Total Trades >= 5 (sufficient sample)

Extracted parameters: {extracted_params}
Backtest result: {backtest_result}
""".strip()


# ─────────────────────────── GitHub API helpers ──────────────────────────────

def _github_request(
    method: str,
    path: str,
    body: dict | None = None,
    token: str = "",
) -> dict | list:
    """Execute a GitHub REST API call. Raises urllib.error.HTTPError on failure."""
    url = f"{_GITHUB_API}{path}"
    data = json.dumps(body).encode() if body else None
    headers = {
        "Accept": "application/vnd.github+json",
        "Content-Type": "application/json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    tok = token or _GITHUB_TOKEN
    if tok:
        headers["Authorization"] = f"token {tok}"

    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode())


def fetch_approved_issues(repo: str = _GITHUB_REPO, token: str = "") -> list[dict]:
    """回傳所有帶 `approved` label 且為 open 的 issues。"""
    path = f"/repos/{repo}/issues?state=open&labels={_APPROVED_LABEL}&per_page=50"
    result = _github_request("GET", path, token=token)
    # 排除 pull requests
    return [i for i in result if not i.get("pull_request")]


def fetch_closed_issues_for_verification(
    repo: str = _GITHUB_REPO,
    token: str = "",
    days: int = _VERIFICATION_WINDOW_DAYS,
) -> list[dict]:
    """Fetch recently updated closed issues for verification evidence review."""
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    path = (
        f"/repos/{repo}/issues?state=closed&sort=updated&direction=desc"
        f"&since={since}&per_page=50"
    )
    result = _github_request("GET", path, token=token)
    return [i for i in result if not i.get("pull_request")]


def fetch_issue_comments(
    repo: str,
    issue_number: int,
    token: str = "",
) -> list[dict]:
    """Fetch all comments for an issue."""
    path = f"/repos/{repo}/issues/{issue_number}/comments?per_page=100"
    result = _github_request("GET", path, token=token)
    return result if isinstance(result, list) else []


def post_issue_comment(
    repo: str,
    issue_number: int,
    body: str,
    token: str = "",
) -> dict:
    """在 issue 上新增留言。"""
    path = f"/repos/{repo}/issues/{issue_number}/comments"
    return _github_request("POST", path, body={"body": body}, token=token)


def add_label(
    repo: str,
    issue_number: int,
    label: str,
    token: str = "",
) -> list:
    path = f"/repos/{repo}/issues/{issue_number}/labels"
    return _github_request("POST", path, body={"labels": [label]}, token=token)


def remove_label(
    repo: str,
    issue_number: int,
    label: str,
    token: str = "",
) -> None:
    path = f"/repos/{repo}/issues/{issue_number}/labels/{label}"
    req = urllib.request.Request(
        f"{_GITHUB_API}{path}",
        method="DELETE",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"token {token or _GITHUB_TOKEN}",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        urllib.request.urlopen(req)
    except urllib.error.HTTPError as e:
        if e.code != 404:
            raise


def issue_has_label(issue: dict, label: str) -> bool:
    return any((lbl.get("name") == label) for lbl in issue.get("labels", []))


def issue_verification_status(issue: dict, comments: list[dict]) -> tuple[bool, list[str]]:
    """Return whether issue closure contains sufficient verification evidence."""
    text_parts = [issue.get("body") or ""]
    text_parts.extend((comment.get("body") or "") for comment in comments)
    haystack = "\n".join(text_parts).lower()

    missing: list[str] = []
    for check_name, keywords in _VERIFICATION_KEYWORDS.items():
        if not any(keyword.lower() in haystack for keyword in keywords):
            missing.append(check_name)

    return len(missing) == 0, missing


def format_verification_followup(issue: dict, missing_checks: list[str]) -> str:
    labels = {
        "before_after": "Before/After data",
        "time_window": "verification time window",
        "regression": "regression test evidence",
    }
    missing_text = ", ".join(labels.get(item, item) for item in missing_checks)
    return (
        "## Verification Follow-up Needed\n\n"
        "This closed issue is missing required verification evidence before it should be treated "
        f"as fully validated.\n\nMissing: {missing_text}\n\n"
        "Please add:\n"
        "- Before/After data\n"
        "- Verification time window\n"
        "- Regression test evidence\n"
    )


def scan_closed_issues_for_verification(
    repo: str,
    token: str,
    dry_run: bool,
    days: int = _VERIFICATION_WINDOW_DAYS,
) -> list[dict]:
    """Detect recently closed issues that are missing verification evidence."""
    issues = fetch_closed_issues_for_verification(repo=repo, token=token, days=days)
    backlog: list[dict] = []

    for issue in issues:
        comments = fetch_issue_comments(repo, issue["number"], token=token)
        verified, missing_checks = issue_verification_status(issue, comments)
        has_label = issue_has_label(issue, _NEEDS_VERIFICATION_LABEL)

        if verified:
            if has_label and not dry_run:
                remove_label(repo, issue["number"], _NEEDS_VERIFICATION_LABEL, token=token)
            continue

        backlog.append(
            {
                "issue_number": issue["number"],
                "issue_title": issue["title"],
                "url": issue.get("html_url"),
                "missing_checks": missing_checks,
            }
        )

        if dry_run:
            continue

        if not has_label:
            add_label(repo, issue["number"], _NEEDS_VERIFICATION_LABEL, token=token)

    return backlog


# ─────────────────────────── 策略參數解析 ────────────────────────────────────

_PARAM_PATTERNS: dict[str, re.Pattern] = {
    "ma_short":                  re.compile(r"ma[_\s-]?short[\s:=]+(\d+)", re.I),
    "ma_long":                   re.compile(r"ma[_\s-]?long[\s:=]+(\d+)", re.I),
    "rsi_period":                re.compile(r"rsi[_\s-]?period[\s:=]+(\d+)", re.I),
    "rsi_entry_max":             re.compile(r"rsi[_\s-]?entry[_\s-]?max[\s:=]+([\d.]+)", re.I),
    "take_profit_pct":           re.compile(r"take[_\s-]?profit[_\s-]?pct[\s:=]+([\d.]+)", re.I),
    "stop_loss_pct":             re.compile(r"stop[_\s-]?loss[_\s-]?pct[\s:=]+([\d.]+)", re.I),
    "trailing_pct":              re.compile(r"trailing[_\s-]?pct[\s:=]+([\d.]+)", re.I),
    "trailing_pct_tight":        re.compile(r"trailing[_\s-]?pct[_\s-]?tight[\s:=]+([\d.]+)", re.I),
    "trailing_profit_threshold": re.compile(r"trailing[_\s-]?profit[_\s-]?threshold[\s:=]+([\d.]+)", re.I),
}


def parse_signal_params(text: str) -> dict:
    """從 issue 文字中擷取策略參數，回傳 dict（只含找到的鍵）。"""
    extracted: dict = {}
    for param, pattern in _PARAM_PATTERNS.items():
        m = pattern.search(text)
        if m:
            val_str = m.group(1)
            extracted[param] = float(val_str) if "." in val_str else int(val_str)
    return extracted


def parse_symbols(text: str) -> list[str]:
    """從 issue 文字中擷取台股代號（4-6 位數字）。"""
    return list(dict.fromkeys(re.findall(r"\b(\d{4,6})\b", text)))


# ─────────────────────────── 回測整合 ────────────────────────────────────────

def run_backtest_for_issue(
    symbols: list[str],
    param_overrides: dict,
    db_path: str = _DB_PATH,
    days: int = _BACKTEST_DAYS,
    capital: float = _BACKTEST_CAPITAL,
) -> dict:
    """執行回測，回傳指標 dict。若無資料或錯誤回傳 None metrics。"""
    from openclaw.backtest_engine import BacktestConfig, run_backtest
    from openclaw.cost_model import CostParams
    from openclaw.signal_logic import SignalParams

    end_dt = datetime.now(tz=timezone(timedelta(hours=8)))
    start_dt = end_dt - timedelta(days=days)
    end_date = end_dt.strftime("%Y-%m-%d")
    start_date = start_dt.strftime("%Y-%m-%d")

    # 預設參數，再套用 issue 中覆寫值
    base_params = {
        "take_profit_pct": 0.02,
        "stop_loss_pct": 0.03,
        "trailing_pct": 0.05,
        "trailing_pct_tight": 0.03,
        "trailing_profit_threshold": 0.50,
        "ma_short": 5,
        "ma_long": 20,
        "rsi_period": 14,
        "rsi_entry_max": 70.0,
    }
    base_params.update(param_overrides)

    # SignalParams 只接受 float 的 pct 參數和 int 的週期參數
    sp = SignalParams(
        take_profit_pct=float(base_params["take_profit_pct"]),
        stop_loss_pct=float(base_params["stop_loss_pct"]),
        trailing_pct=float(base_params["trailing_pct"]),
        trailing_pct_tight=float(base_params["trailing_pct_tight"]),
        trailing_profit_threshold=float(base_params["trailing_profit_threshold"]),
        ma_short=int(base_params["ma_short"]),
        ma_long=int(base_params["ma_long"]),
        rsi_period=int(base_params["rsi_period"]),
        rsi_entry_max=float(base_params["rsi_entry_max"]),
    )

    cfg = BacktestConfig(
        symbols=symbols or ["2330", "2317", "2454"],  # fallback: 大型股
        start_date=start_date,
        end_date=end_date,
        initial_capital=capital,
        signal_params=sp,
        cost_params=CostParams(),
    )

    result = run_backtest(cfg, db_path)
    m = result.metrics

    return {
        "symbols": cfg.symbols,
        "start_date": start_date,
        "end_date": end_date,
        "signal_params": base_params,
        "total_trades": m.total_trades,
        "total_return_pct": round(m.total_return_pct, 2),
        "annualized_return_pct": round(m.annualized_return_pct, 2),
        "sharpe_ratio": round(m.sharpe_ratio, 3),
        "max_drawdown_pct": round(m.max_drawdown_pct, 2),
        "win_rate": round(m.win_rate * 100, 1),
        "profit_factor": round(m.profit_factor, 2),
        "avg_holding_days": round(m.avg_holding_days, 1),
    }


# ─────────────────────────── 驗證判斷 ────────────────────────────────────────

def evaluate_backtest(metrics: dict) -> tuple[bool, str]:
    """
    判斷回測結果是否通過門檻。
    回傳 (passed: bool, reason: str)
    """
    reasons = []

    if metrics["total_trades"] < 5:
        reasons.append(f"交易次數不足（{metrics['total_trades']} < 5）")

    if metrics["sharpe_ratio"] < 0.5:
        reasons.append(f"Sharpe Ratio 過低（{metrics['sharpe_ratio']:.3f} < 0.5）")

    if metrics["max_drawdown_pct"] > 20.0:
        reasons.append(f"最大回撤過大（{metrics['max_drawdown_pct']:.1f}% > 20%）")

    if reasons:
        return False, "；".join(reasons)
    return True, "通過所有門檻"


# ─────────────────────────── 報告格式化 ──────────────────────────────────────

def format_backtest_comment(
    issue_number: int,
    metrics: dict,
    extracted_params: dict,
    passed: bool,
    reason: str,
) -> str:
    """產出 GitHub Issue comment markdown。"""
    now_twn = datetime.now(tz=timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M")
    verdict_icon = "✅" if passed else "❌"
    verdict_text = "**PASSED** — 策略變更建議採用" if passed else "**FAILED** — 策略變更不建議採用"

    params_md = "\n".join(
        f"  - `{k}`: `{v}`" for k, v in extracted_params.items()
    ) if extracted_params else "  - （使用預設參數）"

    symbols_str = ", ".join(f"`{s}`" for s in metrics["symbols"])

    return f"""## 🤖 Coder Agent 回測報告

> 自動產出時間：{now_twn} (TWN) | Issue #{issue_number}

### 策略參數
{params_str(extracted_params)}

### 回測設定
- 標的：{symbols_str}
- 期間：`{metrics['start_date']}` → `{metrics['end_date']}`（約 {_BACKTEST_DAYS} 日）
- 初始資金：`{_BACKTEST_CAPITAL:,.0f}` TWD

### 績效指標

| 指標 | 數值 | 門檻 |
|------|------|------|
| 總報酬 | `{metrics['total_return_pct']:+.2f}%` | — |
| 年化報酬 | `{metrics['annualized_return_pct']:+.2f}%` | — |
| **Sharpe Ratio** | `{metrics['sharpe_ratio']:.3f}` | ≥ 0.5 |
| **最大回撤** | `{metrics['max_drawdown_pct']:.2f}%` | ≤ 20% |
| 勝率 | `{metrics['win_rate']:.1f}%` | — |
| Profit Factor | `{metrics['profit_factor']:.2f}` | — |
| 平均持倉天數 | `{metrics['avg_holding_days']:.1f}` 天 | — |
| **交易次數** | `{metrics['total_trades']}` | ≥ 5 |

### 驗證結論

{verdict_icon} {verdict_text}

> {reason}

---
*由 AI Trader Coder Agent 自動產出。如有疑問請在 Issue 中回覆。*
"""


def params_str(extracted: dict) -> str:
    if not extracted:
        return "- （使用預設參數，issue 中未指定覆寫值）"
    return "\n".join(f"- `{k}`: `{v}`" for k, v in extracted.items())


# ─────────────────────────── 主流程 ──────────────────────────────────────────

def process_issue(
    issue: dict,
    repo: str,
    db_path: str,
    token: str,
    dry_run: bool,
) -> tuple[bool, dict | None]:
    """處理單一 approved issue。回傳 (success, result_dict)。"""
    number = issue["number"]
    title = issue["title"]
    body = issue.get("body") or ""
    full_text = f"{title}\n{body}"

    print(f"\n  Issue #{number}: {title}")

    # 1. 解析策略參數與標的
    extracted_params = parse_signal_params(full_text)
    symbols = parse_symbols(full_text)
    print(f"    Extracted params: {extracted_params}")
    print(f"    Symbols: {symbols}")

    # 2. 執行回測
    try:
        metrics = run_backtest_for_issue(
            symbols=symbols,
            param_overrides=extracted_params,
            db_path=db_path,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"    [ERROR] Backtest failed: {exc}")
        metrics = {
            "symbols": symbols or [],
            "start_date": "N/A",
            "end_date": "N/A",
            "signal_params": {},
            "total_trades": 0,
            "total_return_pct": 0.0,
            "annualized_return_pct": 0.0,
            "sharpe_ratio": 0.0,
            "max_drawdown_pct": 0.0,
            "win_rate": 0.0,
            "profit_factor": 0.0,
            "avg_holding_days": 0.0,
        }

    # 3. 評估
    passed, reason = evaluate_backtest(metrics)
    print(f"    Result: {'PASSED' if passed else 'FAILED'} — {reason}")

    # 4. 格式化報告
    comment_body = format_backtest_comment(number, metrics, extracted_params, passed, reason)

    # 組裝結果供 Evening 報告
    result = {
        "issue_number": number,
        "issue_title": title,
        "passed": passed,
        "reason": reason,
        "metrics": metrics,
        "extracted_params": extracted_params,
    }

    if dry_run:
        print("    [dry-run] Would post comment:")
        print("    " + "\n    ".join(comment_body.splitlines()[:10]) + "\n    ...")
        return True, result

    # 5. 回寫 issue comment
    try:
        post_issue_comment(repo, number, comment_body, token=token)
        print(f"    Posted comment to issue #{number}")
    except Exception as exc:
        print(f"    [ERROR] Failed to post comment: {exc}")
        return False, result

    return True, result


def save_results_state(
    results: list[dict],
    verification_backlog: list[dict] | None = None,
    state_path: str | Path = _RESULTS_STATE_FILE,
) -> None:
    """將回測結果儲存到 config/coder_agent_results.json（供 Evening 報告讀取）。"""
    now_twn = datetime.now(tz=timezone(timedelta(hours=8))).isoformat()
    state = {
        "generated_at": now_twn,
        "results": results,
        "verification_backlog": verification_backlog or [],
    }
    try:
        Path(state_path).parent.mkdir(parents=True, exist_ok=True)
        Path(state_path).write_text(json.dumps(state, ensure_ascii=False, indent=2))
    except OSError as exc:
        print(f"[WARN] Failed to save results state: {exc}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="掃描 GitHub approved issues 並執行回測，結果回寫 issue comment"
    )
    parser.add_argument("--dry-run", action="store_true", help="不實際呼叫 GitHub API")
    parser.add_argument("--db", default=_DB_PATH, help="SQLite DB 路徑")
    parser.add_argument("--repo", default=_GITHUB_REPO, help="owner/repo")
    parser.add_argument("--token", default=_GITHUB_TOKEN, help="GitHub token")
    parser.add_argument(
        "--verification-window-days",
        type=int,
        default=_VERIFICATION_WINDOW_DAYS,
        help="只掃描最近 N 天內更新的 closed issues",
    )
    args = parser.parse_args(argv)

    if not args.token and not args.dry_run:
        print("[ERROR] GITHUB_TOKEN 未設定，請設定環境變數或使用 --token")
        return 1

    print(f"[check_approved_issues] repo={args.repo} db={args.db} dry_run={args.dry_run}")

    # 1. 取得 approved issues
    try:
        issues = fetch_approved_issues(repo=args.repo, token=args.token)
    except Exception as exc:
        print(f"[ERROR] Failed to fetch issues: {exc}")
        return 1

    if not issues:
        print("No approved issues found.")
    else:
        print(f"Found {len(issues)} approved issue(s).")

    # 2. 逐一處理
    errors = 0
    all_results: list[dict] = []
    for issue in issues:
        ok, result = process_issue(
            issue=issue,
            repo=args.repo,
            db_path=args.db,
            token=args.token,
            dry_run=args.dry_run,
        )
        if not ok:
            errors += 1
        if result:
            all_results.append(result)

    # 3. 掃描已關閉 issue 的驗證證據
    verification_backlog: list[dict] = []
    try:
        verification_backlog = scan_closed_issues_for_verification(
            repo=args.repo,
            token=args.token,
            dry_run=args.dry_run,
            days=args.verification_window_days,
        )
    except Exception as exc:
        print(f"[ERROR] Failed to scan closed issues for verification: {exc}")
        if not args.dry_run:
            errors += 1

    if verification_backlog:
        print(f"Found {len(verification_backlog)} closed issue(s) missing verification evidence.")
    else:
        print("No closed issues are missing verification evidence.")

    # 4. 儲存結果供 Evening 報告讀取
    if not args.dry_run:
        save_results_state(all_results, verification_backlog=verification_backlog)

    succeeded = max(len(issues) - errors, 0)
    print(f"\nDone. {succeeded}/{len(issues)} succeeded.")
    return 0 if errors == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
