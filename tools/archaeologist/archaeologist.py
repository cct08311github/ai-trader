"""Code Archaeologist — main controller.

Orchestrates: stale detection -> dead code detection -> duplication detection -> reporting.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import yaml

from tools.archaeologist.dead_code_detector import find_dead_code
from tools.archaeologist.duplication_detector import find_duplicates
from tools.archaeologist.issue_creator import create_issues
from tools.archaeologist.models import ArchaeologistReport, Finding
from tools.archaeologist.stale_detector import find_stale_files

_DEFAULT_CONFIG = Path(__file__).parent / "config.yaml"


def _load_config(config_path: str) -> dict:
    with open(config_path, "r") as f:
        return yaml.safe_load(f)


def run_archaeologist(
    config_path: Optional[str] = None,
    dry_run: bool = False,
) -> ArchaeologistReport:
    """Run the full archaeologist pipeline.

    Args:
        config_path: Path to YAML config. Defaults to tools/archaeologist/config.yaml.
        dry_run: If True, skip GitHub issue creation.

    Returns:
        ArchaeologistReport with all findings.
    """
    cfg_path = config_path or str(_DEFAULT_CONFIG)
    config = _load_config(cfg_path)

    threshold_days = config.get("stale_threshold_days", 180)
    max_issues = config.get("max_issues_per_run", 5)
    exclude = config.get("exclude_patterns", [])

    reports: list[ArchaeologistReport] = []

    for repo_cfg in config.get("repos", []):
        repo_path = str(Path(cfg_path).parent.parent.parent / repo_cfg["path"])
        repo_name = repo_cfg.get("name", "unknown")
        language = repo_cfg.get("language", "python")

        report = ArchaeologistReport(repo_name=repo_name)

        # --- 1. Stale files ---
        try:
            stale = find_stale_files(repo_path, days_threshold=threshold_days, exclude_patterns=exclude)
            report.stale_files = stale
            if stale:
                top = stale[:10]
                file_list = ", ".join(f.path for f in top)
                report.findings.append(Finding(
                    finding_type="stale",
                    summary=f"{len(stale)} files not modified in {threshold_days}+ days",
                    details=f"Found {len(stale)} stale files. Top offenders: {file_list}",
                    files=[f.path for f in stale],
                ))
        except Exception as exc:
            report.errors.append(f"stale_detector: {exc}")

        # --- 2. Dead code ---
        try:
            dead = find_dead_code(repo_path, language=language, exclude_patterns=exclude)
            report.dead_code = dead
            if dead:
                report.findings.append(Finding(
                    finding_type="dead_code",
                    summary=f"{len(dead)} potentially unreferenced modules",
                    details="\n".join(f"- `{d.path}`: {d.reason}" for d in dead[:15]),
                    files=[d.path for d in dead],
                ))
        except Exception as exc:
            report.errors.append(f"dead_code_detector: {exc}")

        # --- 3. Duplication ---
        try:
            dupes = find_duplicates(repo_path, exclude_patterns=exclude)
            report.duplicates = dupes
            if dupes:
                report.findings.append(Finding(
                    finding_type="duplication",
                    summary=f"{len(dupes)} near-duplicate file pairs",
                    details="\n".join(
                        f"- `{g.files[0]}` <-> `{g.files[1]}` (similarity: {g.similarity_score})"
                        for g in dupes[:10]
                    ),
                    files=[f for g in dupes for f in g.files],
                ))
        except Exception as exc:
            report.errors.append(f"duplication_detector: {exc}")

        # --- 4. Create issues ---
        if not dry_run and report.findings:
            try:
                urls = create_issues(report.findings, repo_name, max_issues=max_issues)
                report.issues_created = urls
            except Exception as exc:
                report.errors.append(f"issue_creator: {exc}")

        reports.append(report)

    # Merge into single report if multiple repos
    if len(reports) == 1:
        return reports[0]

    merged = ArchaeologistReport(repo_name="multi-repo")
    for r in reports:
        merged.stale_files.extend(r.stale_files)
        merged.dead_code.extend(r.dead_code)
        merged.duplicates.extend(r.duplicates)
        merged.findings.extend(r.findings)
        merged.issues_created.extend(r.issues_created)
        merged.errors.extend(r.errors)
    return merged


if __name__ == "__main__":
    import json
    from dataclasses import asdict

    report = run_archaeologist(dry_run=True)
    print(json.dumps(asdict(report), indent=2, default=str))
