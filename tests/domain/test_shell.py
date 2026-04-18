"""Tests for the shell.run helper, especially credential redaction."""

from __future__ import annotations

import pytest

from otcli.domain import shell


class TestRedactCommandForLogging:
    def test_plain_command_unchanged(self) -> None:
        assert shell._redact_command_for_logging(['ls', '-la', '/tmp']) == [
            'ls',
            '-la',
            '/tmp',
        ]

    def test_redacts_master_pwd_form_field(self) -> None:
        cmd = [
            'curl',
            '-X',
            'POST',
            '-F',
            'master_pwd=s3cret',
            '-F',
            'name=dbtest',
            'http://example/',
        ]
        assert shell._redact_command_for_logging(cmd) == [
            'curl',
            '-X',
            'POST',
            '-F',
            'master_pwd=***REDACTED***',
            '-F',
            'name=dbtest',
            'http://example/',
        ]

    @pytest.mark.parametrize(
        'key',
        ['password', 'passwd', 'pwd', 'secret', 'api_token', 'TOKEN', 'AccessKey'],
    )
    def test_redacts_common_credential_keys(self, key: str) -> None:
        cmd = ['curl', '-F', f'{key}=value123', 'http://x']
        redacted = shell._redact_command_for_logging(cmd)
        assert redacted[2] == f'{key}=***REDACTED***'

    def test_redacts_env_style_assignment(self) -> None:
        # Some callers interpolate secrets directly, e.g. PGPASSWORD=odoo psql.
        cmd = ['env', 'PGPASSWORD=odoo', 'psql', '-c', 'SELECT 1;']
        redacted = shell._redact_command_for_logging(cmd)
        assert redacted[1] == 'PGPASSWORD=***REDACTED***'

    def test_does_not_redact_non_secret_equals(self) -> None:
        cmd = ['curl', '-F', 'name=user', 'http://x']
        assert shell._redact_command_for_logging(cmd) == cmd

    def test_returns_copy_not_original(self) -> None:
        cmd = ['curl', '-F', 'master_pwd=x', 'http://x']
        out = shell._redact_command_for_logging(cmd)
        assert out is not cmd
        assert cmd[2] == 'master_pwd=x', 'original list must not be mutated'
