"""Test API key security + IP allowlist (v4 #12)."""

import os
import pytest

from openclaw.secrets import get_secret
from openclaw.network_allowlist import check_ip_whitelist, enforce_network_security, NetworkSecurityError


def test_get_secret_env_overrides_dotenv_and_keychain(monkeypatch, tmp_path):
    key = "TEST_SECRET_KEY"

    dotenv = tmp_path / ".env"
    dotenv.write_text(f"{key}=from_dotenv\n", encoding="utf-8")
    monkeypatch.setenv("OPENCLAW_DOTENV_PATH", str(dotenv))

    class DummyKeyring:
        @staticmethod
        def get_password(service, account):
            return "from_keychain"

    import openclaw.secrets as secrets_mod

    monkeypatch.setattr(secrets_mod, "keyring", DummyKeyring)
    monkeypatch.setenv(key, "from_env")

    assert get_secret(key) == "from_env"


def test_get_secret_dotenv_fallback(monkeypatch, tmp_path):
    key = "TEST_SECRET_KEY_2"
    monkeypatch.delenv(key, raising=False)

    dotenv = tmp_path / ".env"
    dotenv.write_text(f"{key}='from_dotenv'\n", encoding="utf-8")
    monkeypatch.setenv("OPENCLAW_DOTENV_PATH", str(dotenv))

    import openclaw.secrets as secrets_mod

    class DummyKeyring:
        @staticmethod
        def get_password(service, account):
            return "from_keychain"

    monkeypatch.setattr(secrets_mod, "keyring", DummyKeyring)

    assert get_secret(key) == "from_dotenv"


def test_get_secret_keychain_fallback(monkeypatch, tmp_path):
    key = "TEST_SECRET_KEY_3"
    monkeypatch.delenv(key, raising=False)

    dotenv = tmp_path / ".env"
    dotenv.write_text("# empty\n", encoding="utf-8")
    monkeypatch.setenv("OPENCLAW_DOTENV_PATH", str(dotenv))

    import openclaw.secrets as secrets_mod

    class DummyKeyring:
        @staticmethod
        def get_password(service, account):
            assert account == key
            return "from_keychain"

    monkeypatch.setattr(secrets_mod, "keyring", DummyKeyring)

    assert get_secret(key) == "from_keychain"


def test_check_ip_whitelist_single_and_cidr():
    assert check_ip_whitelist("203.0.113.10", ["203.0.113.10"]) is True
    assert check_ip_whitelist("203.0.113.10", ["203.0.113.11"]) is False
    assert check_ip_whitelist("203.0.113.10", ["203.0.113.0/24"]) is True
    assert check_ip_whitelist("203.0.113.10", ["203.0.112.0/24"]) is False


def test_check_ip_whitelist_ignores_invalid_entries():
    assert check_ip_whitelist("203.0.113.10", ["not-a-cidr", "203.0.113.0/24"]) is True


def test_enforce_network_security_raises_when_denied():
    with pytest.raises(NetworkSecurityError):
        enforce_network_security(current_ip="203.0.113.10", whitelist=["203.0.113.0/28"])


def test_enforce_network_security_passes_when_allowed():
    ip = enforce_network_security(current_ip="203.0.113.10", whitelist=["203.0.113.0/24"])
    assert ip == "203.0.113.10"
