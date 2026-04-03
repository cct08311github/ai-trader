"""memory_analyzer.py — 分析 Claude Code memory 檔案的健康狀態。"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple


@dataclass
class MemoryEntry:
    """單一 memory 檔案的結構化資訊。"""
    file_path: str
    name: str
    description: str
    mem_type: str
    age_days: int
    needs_review: bool


@dataclass
class MemoryAnalysis:
    """Memory 分析結果。"""
    total: int = 0
    by_type: Dict[str, int] = field(default_factory=dict)
    stale_count: int = 0
    duplicates: List[Tuple[str, str]] = field(default_factory=list)
    oldest: Optional[MemoryEntry] = None
    newest: Optional[MemoryEntry] = None
    entries: List[MemoryEntry] = field(default_factory=list)


def _parse_frontmatter(content: str) -> Dict[str, str]:
    """從 YAML frontmatter 解析 name, description, type。"""
    match = re.match(r"^---\s*\n(.*?)\n---", content, re.DOTALL)
    if not match:
        return {}
    result: Dict[str, str] = {}
    for line in match.group(1).strip().splitlines():
        if ":" in line:
            key, _, value = line.partition(":")
            result[key.strip()] = value.strip()
    return result


def _file_age_days(file_path: Path) -> int:
    """計算檔案修改日期距今天數。"""
    mtime = os.path.getmtime(file_path)
    mtime_dt = datetime.fromtimestamp(mtime, tz=timezone.utc)
    now = datetime.now(tz=timezone.utc)
    return (now - mtime_dt).days


def analyze_memories(
    memory_dirs: List[str],
    stale_days: int = 30,
) -> MemoryAnalysis:
    """掃描所有 memory 目錄，產出健康報告。

    Args:
        memory_dirs: memory 目錄路徑列表（支援 ~ 展開）。
        stale_days: 超過此天數標記為需要 review。

    Returns:
        MemoryAnalysis 結果。
    """
    analysis = MemoryAnalysis()
    desc_map: Dict[str, str] = {}  # description -> file_path（偵測重複用）

    for dir_path_str in memory_dirs:
        dir_path = Path(os.path.expanduser(dir_path_str))
        if not dir_path.is_dir():
            continue
        for md_file in sorted(dir_path.glob("*.md")):
            if md_file.name == "MEMORY.md":
                continue
            content = md_file.read_text(encoding="utf-8", errors="replace")
            fm = _parse_frontmatter(content)
            if not fm:
                continue

            name = fm.get("name", md_file.stem)
            description = fm.get("description", "")
            mem_type = fm.get("type", "unknown")
            age = _file_age_days(md_file)
            needs_review = age >= stale_days

            entry = MemoryEntry(
                file_path=str(md_file),
                name=name,
                description=description,
                mem_type=mem_type,
                age_days=age,
                needs_review=needs_review,
            )
            analysis.entries.append(entry)
            analysis.total += 1
            analysis.by_type[mem_type] = analysis.by_type.get(mem_type, 0) + 1

            if needs_review:
                analysis.stale_count += 1

            # 偵測重複 description
            if description:
                if description in desc_map:
                    analysis.duplicates.append((desc_map[description], str(md_file)))
                else:
                    desc_map[description] = str(md_file)

            # 追蹤最新 / 最舊
            if analysis.oldest is None or age > analysis.oldest.age_days:
                analysis.oldest = entry
            if analysis.newest is None or age < analysis.newest.age_days:
                analysis.newest = entry

    return analysis
