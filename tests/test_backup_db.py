"""tests/test_backup_db.py — bin/run_backup.sh 單元測試 [Issue #279]"""
from __future__ import annotations

import os
import sqlite3
import subprocess
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKUP_SCRIPT = REPO_ROOT / "bin" / "run_backup.sh"


def _make_db(tmp_path: Path) -> Path:
    """建立含 eod_prices 資料的測試 SQLite。"""
    db = tmp_path / "trades.db"
    conn = sqlite3.connect(str(db))
    conn.execute("CREATE TABLE eod_prices (trade_date TEXT, symbol TEXT, close REAL)")
    conn.execute("INSERT INTO eod_prices VALUES ('2024-01-02', '2330', 560.0)")
    conn.commit()
    conn.close()
    return db


def _run_backup(db_path: Path, backup_dir: Path, retain: int = 30) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(BACKUP_SCRIPT)],
        env={
            **os.environ,
            "DB_PATH": str(db_path),
            "BACKUP_DIR": str(backup_dir),
            "BACKUP_RETAIN": str(retain),
        },
        capture_output=True,
        text=True,
    )


class TestRunBackup:
    def test_creates_backup_file(self, tmp_path):
        db = _make_db(tmp_path)
        backup_dir = tmp_path / "backup"
        result = _run_backup(db, backup_dir)
        assert result.returncode == 0, result.stderr
        backups = list(backup_dir.glob("trades_*.sql.gz"))
        assert len(backups) == 1

    def test_backup_file_is_nonempty(self, tmp_path):
        db = _make_db(tmp_path)
        backup_dir = tmp_path / "backup"
        _run_backup(db, backup_dir)
        backup = next((backup_dir).glob("trades_*.sql.gz"))
        assert backup.stat().st_size > 0

    def test_backup_dir_created_if_missing(self, tmp_path):
        db = _make_db(tmp_path)
        backup_dir = tmp_path / "nested" / "backup"
        assert not backup_dir.exists()
        result = _run_backup(db, backup_dir)
        assert result.returncode == 0
        assert backup_dir.exists()

    def test_skips_gracefully_when_db_missing(self, tmp_path):
        backup_dir = tmp_path / "backup"
        result = _run_backup(tmp_path / "nonexistent.db", backup_dir)
        assert result.returncode == 0
        assert "WARN" in result.stdout
        assert not list(backup_dir.glob("trades_*.sql.gz"))

    def test_prunes_old_backups_beyond_retain(self, tmp_path):
        db = _make_db(tmp_path)
        backup_dir = tmp_path / "backup"
        backup_dir.mkdir()

        # 預先建 5 個假備份（timestamps 遞增）
        for i in range(5):
            (backup_dir / f"trades_2024010{i}_000000.sql.gz").write_bytes(b"x")

        # retain=3 → 跑完後最多 3+1=4 個（新的1個 + 保留3個）
        result = _run_backup(db, backup_dir, retain=3)
        assert result.returncode == 0
        remaining = list(backup_dir.glob("trades_*.sql.gz"))
        assert len(remaining) <= 4  # 3 old retained + 1 new

    def test_ecosystem_config_contains_backup_entry(self):
        """ecosystem.config.js 應包含 ai-trader-db-backup entry。"""
        config = (REPO_ROOT / "ecosystem.config.js").read_text()
        assert "ai-trader-db-backup" in config
        assert "run_backup.sh" in config
        assert "0 2 * * *" in config

    def test_backup_script_is_executable(self):
        assert os.access(BACKUP_SCRIPT, os.X_OK), f"{BACKUP_SCRIPT} 未設定 executable bit"
