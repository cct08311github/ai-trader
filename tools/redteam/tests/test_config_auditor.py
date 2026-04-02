"""Tests for config_auditor module."""
import os
import stat
import tempfile

import pytest

from tools.redteam.config_auditor import (
    check_env_permissions,
    check_hardcoded_secrets,
    check_nginx_headers,
    audit_config,
)


class TestCheckEnvPermissions:
    def test_detects_world_readable_env(self):
        with tempfile.TemporaryDirectory() as d:
            env_file = os.path.join(d, ".env")
            with open(env_file, "w") as f:
                f.write("SECRET=value\n")
            os.chmod(env_file, 0o644)

            findings = check_env_permissions(d)
            assert len(findings) == 1
            assert "world-readable" in findings[0].title

    def test_ignores_secure_env(self):
        with tempfile.TemporaryDirectory() as d:
            env_file = os.path.join(d, ".env")
            with open(env_file, "w") as f:
                f.write("SECRET=value\n")
            os.chmod(env_file, 0o600)

            findings = check_env_permissions(d)
            assert len(findings) == 0

    def test_ignores_env_example(self):
        with tempfile.TemporaryDirectory() as d:
            env_file = os.path.join(d, ".env.example")
            with open(env_file, "w") as f:
                f.write("SECRET=placeholder\n")
            os.chmod(env_file, 0o644)

            findings = check_env_permissions(d)
            assert len(findings) == 0


class TestCheckHardcodedSecrets:
    def test_detects_bot_token(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".js", delete=False) as f:
            f.write('const config = {\n')
            f.write('  WATCHER_TELEGRAM_BOT_TOKEN: "8773751510:AAHFORPaipYCA_993wx8B5fGH_eOAq5jqP0",\n')
            f.write('};\n')
            f.flush()

            findings = check_hardcoded_secrets(f.name)
            assert len(findings) >= 1
            assert findings[0].category == "hardcoded-secret"
            # Verify the actual token value is masked in evidence
            for finding in findings:
                assert "AAHFORPaipYCA_993wx8B5fGH_eOAq5jqP0" not in finding.evidence

        os.unlink(f.name)

    def test_detects_api_key(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".ts", delete=False) as f:
            f.write('export const firebaseConfig = {\n')
            f.write('  apiKey: "AIzaSyD1234567890abcdefghijklmnop",\n')
            f.write('};\n')
            f.flush()

            findings = check_hardcoded_secrets(f.name)
            assert len(findings) >= 1
            assert any(f.category == "hardcoded-api-key" for f in findings)

        os.unlink(f.name)

    def test_clean_file_no_findings(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".js", delete=False) as f:
            f.write('const x = 1;\nconst y = "hello";\n')
            f.flush()

            findings = check_hardcoded_secrets(f.name)
            assert len(findings) == 0

        os.unlink(f.name)

    def test_nonexistent_file(self):
        findings = check_hardcoded_secrets("/nonexistent/file.js")
        assert findings == []


class TestCheckNginxHeaders:
    def test_returns_empty_for_missing_dir(self):
        assert check_nginx_headers("/nonexistent/") == []

    def test_detects_missing_headers(self):
        with tempfile.TemporaryDirectory() as d:
            conf = os.path.join(d, "default.conf")
            with open(conf, "w") as f:
                f.write("server { listen 80; }\n")

            findings = check_nginx_headers(d)
            # Should detect all 4 missing headers
            assert len(findings) == 4
            titles = {f.title for f in findings}
            assert "Missing header: X-Content-Type-Options" in titles


class TestAuditConfig:
    def test_scans_ecosystem_config(self):
        with tempfile.TemporaryDirectory() as d:
            eco = os.path.join(d, "ecosystem.config.js")
            with open(eco, "w") as f:
                f.write('BOT_TOKEN: "8773751510:AAHFORPaipYCA_993wx8B5fGH_eOAq5jqP0"\n')

            findings = audit_config(d, nginx_dir="/nonexistent/")
            secret_findings = [f for f in findings if f.category == "hardcoded-secret"]
            assert len(secret_findings) >= 1
