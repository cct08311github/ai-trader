from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Optional
from openclaw.path_utils import get_repo_root

try:  # optional dependency
    import keyring  # type: ignore
except Exception:  # pragma: no cover
    keyring = None


def _project_root() -> Path:
    # .../src/openclaw/secrets.py -> parents[0]=openclaw, [1]=src, [2]=project root
    return get_repo_root()


def _parse_dotenv_value(raw: str) -> str:
    v = raw.strip()
    if (v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'")):
        v = v[1:-1]
    return v


def _get_from_dotenv(key: str, *, dotenv_path: Optional[str] = None) -> str:
    p = dotenv_path or os.getenv("OPENCLAW_DOTENV_PATH") or ".env"
    path = Path(p)
    if not path.is_absolute():
        # resolve relative to project root first
        candidate = _project_root() / path
        if candidate.exists():
            path = candidate
        else:
            path = Path.cwd() / path

    if not path.exists() or not path.is_file():
        return ""

    try:
        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            if s.startswith("export "):
                s = s[len("export ") :].strip()
            if "=" not in s:
                continue
            k, v = s.split("=", 1)
            if k.strip() == key:
                return _parse_dotenv_value(v)
    except Exception:
        return ""

    return ""


def _get_from_keychain(
    key: str, *, keychain_service: Optional[str] = None, keychain_account: Optional[str] = None
) -> str:
    service = keychain_service or os.getenv("OPENCLAW_KEYCHAIN_SERVICE") or "openclaw"
    account = keychain_account or os.getenv("OPENCLAW_KEYCHAIN_ACCOUNT") or key

    # Prefer keyring (supports macOS Keychain via backend)
    if keyring is not None:
        try:
            v = keyring.get_password(service, account)  # type: ignore[attr-defined]
            if v:
                return str(v).strip()
        except Exception:
            pass

    # Fallback to `security` CLI (macOS)
    try:
        out = subprocess.check_output(
            [
                "security",
                "find-generic-password",
                "-s",
                service,
                "-a",
                account,
                "-w",
            ],
            text=True,
        )
        v = out.strip()
        if v:
            return v
    except Exception:
        pass

    return ""


def get_secret(
    key: str,
    *,
    dotenv_path: Optional[str] = None,
    keychain_service: Optional[str] = None,
    keychain_account: Optional[str] = None,
) -> str:
    """Resolve secret in priority order:

    1) Environment Variable
    2) .env file
    3) macOS Keychain (via keyring, fallback to `security` CLI)

    Raises RuntimeError if not found.
    """

    value = os.getenv(key, "").strip()
    if value:
        return value

    value = _get_from_dotenv(key, dotenv_path=dotenv_path).strip()
    if value:
        return value

    value = _get_from_keychain(
        key,
        keychain_service=keychain_service,
        keychain_account=keychain_account,
    ).strip()
    if value:
        return value

    service = keychain_service or os.getenv("OPENCLAW_KEYCHAIN_SERVICE") or "openclaw"
    account = keychain_account or os.getenv("OPENCLAW_KEYCHAIN_ACCOUNT") or key
    raise RuntimeError(
        f"missing secret: {key}; set env var, .env, or macOS keychain ({service}/{account})"
    )
