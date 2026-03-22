#!/usr/bin/env python3
"""check_closed_issue_verification.py — 已關閉 Issue 效果追蹤 (#388)

掃描最近 30 天關閉的策略相關 issue，檢查是否附有驗證數據。
未驗證的 issue 加上 `needs-verification` label。

用法：
    python tools/check_closed_issue_verification.py [--dry-run]

環境變數：
    GITHUB_TOKEN    GitHub Personal Access Token
    GITHUB_REPO     owner/repo（預設 cct08311github/ai-trader）
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta


REPO = os.environ.get("GITHUB_REPO", "cct08311github/ai-trader")
# Labels that indicate strategy-related issues needing verification
STRATEGY_LABELS = {"enhancement", "bug", "P0", "P1", "P2"}
# Keywords in issue body that indicate verification was provided
VERIFICATION_KEYWORDS = [
    "before/after",
    "before:",
    "after:",
    "驗證",
    "verification",
    "verified",
    "confirmed",
    "觀察",
    "交易日確認",
]


def _gh(*args: str) -> str:
    """Run gh CLI and return stdout."""
    result = subprocess.run(
        ["gh", *args],
        capture_output=True, text=True, timeout=30,
    )
    if result.returncode != 0:
        print(f"gh error: {result.stderr.strip()}", file=sys.stderr)
        return ""
    return result.stdout.strip()


def get_recently_closed_issues(days: int = 30) -> list[dict]:
    """Get issues closed in the last N days."""
    since = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    raw = _gh(
        "issue", "list", "--repo", REPO,
        "--state", "closed",
        "--limit", "50",
        "--json", "number,title,labels,closedAt,body",
    )
    if not raw:
        return []
    issues = json.loads(raw)
    # Filter by close date
    return [
        i for i in issues
        if i.get("closedAt", "")[:10] >= since
    ]


def needs_verification(issue: dict) -> bool:
    """Check if an issue needs verification.

    Returns True if:
    1. It has strategy-related labels
    2. Its body/comments don't contain verification evidence
    3. It doesn't already have 'needs-verification' label
    """
    labels = {l["name"] for l in issue.get("labels", [])}

    # Skip if already tagged
    if "needs-verification" in labels:
        return False

    # Only check strategy-related issues
    if not labels & STRATEGY_LABELS:
        return False

    body = (issue.get("body") or "").lower()
    for keyword in VERIFICATION_KEYWORDS:
        if keyword.lower() in body:
            return False

    return True


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--days", type=int, default=30)
    args = parser.parse_args()

    issues = get_recently_closed_issues(args.days)
    print(f"Found {len(issues)} recently closed issues")

    unverified = [i for i in issues if needs_verification(i)]
    print(f"  {len(unverified)} need verification")

    for issue in unverified:
        number = issue["number"]
        title = issue["title"]
        print(f"  #{number}: {title}")

        if not args.dry_run:
            _gh(
                "issue", "edit", str(number),
                "--repo", REPO,
                "--add-label", "needs-verification",
            )
            _gh(
                "issue", "comment", str(number),
                "--repo", REPO,
                "--body",
                "⚠️ **效果未驗證** — 此 issue 關閉時未附 Before/After 數據或驗證時間範圍。"
                "\n\n請補充驗證資訊後移除 `needs-verification` label。"
                "\n\n_Auto-detected by check_closed_issue_verification.py (#388)_",
            )
            print(f"    → labeled + commented")

    if not unverified:
        print("  All recently closed issues have verification evidence ✓")


if __name__ == "__main__":
    main()
