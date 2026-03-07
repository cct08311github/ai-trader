from __future__ import annotations

import hashlib
import json
import sqlite3
from typing import Any


def ensure_llm_trace_governance_columns(conn: sqlite3.Connection) -> None:
    migrations = [
        "ALTER TABLE llm_traces ADD COLUMN metadata_json TEXT NOT NULL DEFAULT '{}'",
        "ALTER TABLE llm_traces ADD COLUMN prompt_version TEXT",
        "ALTER TABLE llm_traces ADD COLUMN model_version TEXT",
        "ALTER TABLE llm_traces ADD COLUMN input_hash TEXT",
        "ALTER TABLE llm_traces ADD COLUMN shadow_mode INTEGER NOT NULL DEFAULT 0",
    ]
    for sql in migrations:
        try:
            conn.execute(sql)
        except sqlite3.OperationalError as e:
            msg = str(e).lower()
            if "duplicate column" not in msg and "cannot add a not null column" not in msg:
                # read-only or incompatible schema should not break trace writes
                if "readonly" in msg:
                    continue
                raise
    try:
        conn.commit()
    except sqlite3.Error:
        pass


def build_governance_metadata(
    *,
    prompt_text: str,
    model: str,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    meta = dict(metadata or {})
    prompt_version = str(meta.get("prompt_version") or "unversioned")
    model_version = str(meta.get("model_version") or meta.get("pinned_model") or model)
    shadow_mode = bool(meta.get("shadow_mode", False))
    input_snapshot = meta.get("input_snapshot")

    hash_source: str
    if input_snapshot is not None:
        try:
            hash_source = json.dumps(input_snapshot, sort_keys=True, ensure_ascii=True)
        except TypeError:
            hash_source = str(input_snapshot)
    else:
        hash_source = prompt_text

    meta.setdefault("prompt_version", prompt_version)
    meta.setdefault("model_version", model_version)
    meta.setdefault("shadow_mode", shadow_mode)
    meta.setdefault("input_hash", hashlib.sha256(hash_source.encode("utf-8")).hexdigest())
    return meta
