"""Tests for secrets.py — 67% → 100% coverage."""
from __future__ import annotations

import subprocess
from unittest.mock import patch, MagicMock

import pytest

from openclaw.secrets import (
    _get_from_dotenv,
    _get_from_keychain,
    _parse_dotenv_value,
    get_secret,
)


# ── _parse_dotenv_value ──────────────────────────────────────────────────────

def test_parse_dotenv_value_plain():
    assert _parse_dotenv_value("hello") == "hello"


def test_parse_dotenv_value_double_quoted():
    assert _parse_dotenv_value('"hello"') == "hello"


def test_parse_dotenv_value_single_quoted():
    assert _parse_dotenv_value("'hello'") == "hello"


# ── _get_from_dotenv ─────────────────────────────────────────────────────────

def test_get_from_dotenv_reads_value(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("MY_KEY=secret_value\n")
    result = _get_from_dotenv("MY_KEY", dotenv_path=str(env_file))
    assert result == "secret_value"


def test_get_from_dotenv_export_prefix(tmp_path):
    """Line 48: handles 'export KEY=value' syntax."""
    env_file = tmp_path / ".env"
    env_file.write_text("export MY_KEY=exported_value\n")
    result = _get_from_dotenv("MY_KEY", dotenv_path=str(env_file))
    assert result == "exported_value"


def test_get_from_dotenv_skips_comments_and_blanks(tmp_path):
    """Lines 46: skip comment lines and blank lines."""
    env_file = tmp_path / ".env"
    env_file.write_text("# comment\n\nMY_KEY=value\n")
    result = _get_from_dotenv("MY_KEY", dotenv_path=str(env_file))
    assert result == "value"


def test_get_from_dotenv_skips_lines_without_equals(tmp_path):
    """Line 52: skip lines without '='."""
    env_file = tmp_path / ".env"
    env_file.write_text("NOTAKEY\nMY_KEY=value\n")
    result = _get_from_dotenv("MY_KEY", dotenv_path=str(env_file))
    assert result == "value"


def test_get_from_dotenv_file_not_found_returns_empty(tmp_path):
    """Line 38: path does not exist → return empty string."""
    result = _get_from_dotenv("ANY_KEY", dotenv_path=str(tmp_path / "nonexistent.env"))
    assert result == ""


def test_get_from_dotenv_key_not_found_returns_empty(tmp_path):
    """Line 53 + loop fallthrough → return ""."""
    env_file = tmp_path / ".env"
    env_file.write_text("OTHER_KEY=other\n")
    result = _get_from_dotenv("MY_KEY", dotenv_path=str(env_file))
    assert result == ""


def test_get_from_dotenv_relative_path_fallback(tmp_path, monkeypatch):
    """Lines 31-35: relative path resolution → candidate at project_root doesn't exist,
    falls back to cwd / path."""
    env_file = tmp_path / ".env"
    env_file.write_text("MY_KEY=from_cwd\n")
    monkeypatch.chdir(tmp_path)
    # Pass a relative path that won't be found at project_root → resolves to cwd
    result = _get_from_dotenv("MY_KEY", dotenv_path=".env")
    assert result == "from_cwd"


# ── _get_from_keychain ───────────────────────────────────────────────────────

def test_get_from_keychain_via_keyring(monkeypatch):
    """Lines 70-79: keyring is available and returns a value."""
    mock_keyring = MagicMock()
    mock_keyring.get_password.return_value = "keyring_secret"
    import openclaw.secrets as secrets_mod
    monkeypatch.setattr(secrets_mod, "keyring", mock_keyring)
    result = _get_from_keychain("MY_KEY")
    assert result == "keyring_secret"


def test_get_from_keychain_keyring_returns_none_falls_back_to_security(monkeypatch):
    """Lines 75-91: keyring returns None, falls back to macOS security CLI."""
    mock_keyring = MagicMock()
    mock_keyring.get_password.return_value = None
    import openclaw.secrets as secrets_mod
    monkeypatch.setattr(secrets_mod, "keyring", mock_keyring)
    with patch("openclaw.secrets.subprocess.check_output", return_value="cli_secret\n"):
        result = _get_from_keychain("MY_KEY")
    assert result == "cli_secret"


def test_get_from_keychain_keyring_exception_falls_back(monkeypatch):
    """Lines 74-75: keyring.get_password raises, falls back to security CLI."""
    mock_keyring = MagicMock()
    mock_keyring.get_password.side_effect = Exception("keyring error")
    import openclaw.secrets as secrets_mod
    monkeypatch.setattr(secrets_mod, "keyring", mock_keyring)
    with patch("openclaw.secrets.subprocess.check_output", return_value="cli_secret\n"):
        result = _get_from_keychain("MY_KEY")
    assert result == "cli_secret"


def test_get_from_keychain_all_fail_returns_empty(monkeypatch):
    """Line 93: both keyring and security CLI fail → return ''."""
    mock_keyring = MagicMock()
    mock_keyring.get_password.return_value = None
    import openclaw.secrets as secrets_mod
    monkeypatch.setattr(secrets_mod, "keyring", mock_keyring)
    with patch("openclaw.secrets.subprocess.check_output", side_effect=subprocess.CalledProcessError(1, "security")):
        result = _get_from_keychain("MY_KEY")
    assert result == ""


def test_get_from_keychain_no_keyring_uses_cli(monkeypatch):
    """Lines 83-91: keyring is None, goes straight to security CLI."""
    import openclaw.secrets as secrets_mod
    monkeypatch.setattr(secrets_mod, "keyring", None)
    with patch("openclaw.secrets.subprocess.check_output", return_value="cli_only\n"):
        result = _get_from_keychain("MY_KEY")
    assert result == "cli_only"


# ── get_secret ───────────────────────────────────────────────────────────────

def test_get_secret_from_env(monkeypatch):
    monkeypatch.setenv("MY_SECRET_KEY", "env_value")
    result = get_secret("MY_SECRET_KEY")
    assert result == "env_value"


def test_get_secret_from_dotenv(monkeypatch, tmp_path):
    monkeypatch.delenv("MY_SECRET_KEY", raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text("MY_SECRET_KEY=dotenv_value\n")
    result = get_secret("MY_SECRET_KEY", dotenv_path=str(env_file))
    assert result == "dotenv_value"


def test_get_secret_raises_when_not_found(monkeypatch):
    """Lines 128-130: all sources fail → RuntimeError."""
    monkeypatch.delenv("MISSING_SECRET_KEY", raising=False)
    import openclaw.secrets as secrets_mod
    monkeypatch.setattr(secrets_mod, "keyring", None)
    with patch("openclaw.secrets.subprocess.check_output", side_effect=Exception("not found")):
        with pytest.raises(RuntimeError, match="missing secret"):
            get_secret("MISSING_SECRET_KEY", dotenv_path="/nonexistent/path/.env")


def test_get_from_dotenv_reads_from_project_root(monkeypatch, tmp_path):
    """Line 33: candidate at project_root exists → use it."""
    import openclaw.secrets as secrets_mod
    # Make _project_root() return tmp_path
    monkeypatch.setattr(secrets_mod, "_project_root", lambda: tmp_path)
    env_file = tmp_path / ".env"
    env_file.write_text("ROOT_KEY=root_value\n")
    result = _get_from_dotenv("ROOT_KEY", dotenv_path=".env")
    assert result == "root_value"


def test_get_from_dotenv_read_exception_returns_empty(monkeypatch, tmp_path):
    """Lines 52-53: exception during read_text → return ''."""
    import openclaw.secrets as secrets_mod
    env_file = tmp_path / ".env"
    env_file.write_text("KEY=value\n")
    with patch("pathlib.Path.read_text", side_effect=PermissionError("no read")):
        result = _get_from_dotenv("KEY", dotenv_path=str(env_file))
    assert result == ""


def test_get_secret_from_keychain(monkeypatch):
    """Line 126 (keychain call continuation): keychain returns value."""
    monkeypatch.delenv("KEYCHAIN_SECRET", raising=False)
    import openclaw.secrets as secrets_mod
    monkeypatch.setattr(secrets_mod, "keyring", None)
    with patch("openclaw.secrets.subprocess.check_output", return_value="kc_value\n"):
        result = get_secret("KEYCHAIN_SECRET", dotenv_path="/nonexistent/path/.env")
    assert result == "kc_value"
