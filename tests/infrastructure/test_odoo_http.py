"""Tests for the HTTP-based Odoo endpoints wrapper.

Ensures that non-2xx responses from ``/web/database/restore`` and
``/web/database/drop`` are surfaced as :class:`OdooCLIError` instead of
being silently reported as success.
"""

from __future__ import annotations

import subprocess
from unittest.mock import patch

import pytest

from otcli.domain.exceptions import OdooCLIError
from otcli.infrastructure import odoo_http


@pytest.fixture()
def configured(fresh_config) -> None:
    fresh_config.update(
        {
            'url': 'http://localhost:8069',
            'db_name': 'test_db',
            'master_pwd': 'admin',
            'db_container_name': 'odoo-db',
        }
    )


def _curl_result(http_code: int, body: str = '') -> subprocess.CompletedProcess:
    """Simulate what ``_run_curl`` would receive from a successful invocation.

    stdout = body + newline + http_code (the -w '\\n%{http_code}' suffix).
    """
    stdout = f'{body}\n{http_code}'
    return subprocess.CompletedProcess(args=['curl'], returncode=0, stdout=stdout, stderr='')


class TestRestoreDatabase:
    def test_success_on_2xx(self, configured) -> None:
        with patch.object(odoo_http, '_run_curl', return_value=_curl_result(200, 'ok')):
            odoo_http.restore_database('backup.zip')  # must not raise

    def test_raises_on_4xx(self, configured) -> None:
        with (
            patch.object(
                odoo_http,
                '_run_curl',
                return_value=_curl_result(400, 'Bad master password'),
            ),
            pytest.raises(OdooCLIError, match='400'),
        ):
            odoo_http.restore_database('backup.zip')

    def test_raises_on_5xx_and_includes_body(self, configured) -> None:
        with (
            patch.object(
                odoo_http,
                '_run_curl',
                return_value=_curl_result(500, 'internal odoo traceback here'),
            ),
            pytest.raises(OdooCLIError) as excinfo,
        ):
            odoo_http.restore_database('backup.zip')
        assert 'internal odoo traceback here' in str(excinfo.value)


class TestDropDatabase:
    def test_success_on_2xx(self, configured) -> None:
        with patch.object(odoo_http, '_run_curl', return_value=_curl_result(200, 'ok')):
            odoo_http.drop_database()

    def test_raises_on_error(self, configured) -> None:
        with (
            patch.object(
                odoo_http,
                '_run_curl',
                return_value=_curl_result(403, 'Forbidden: wrong master_pwd'),
            ),
            pytest.raises(OdooCLIError, match='403'),
        ):
            odoo_http.drop_database()


class TestCurlNotInstalled:
    def test_surfaces_as_odoocli_error(self, configured) -> None:
        def raises_filenotfound(*_a, **_kw):
            raise FileNotFoundError('curl not found')

        with (
            patch.object(odoo_http, '_run_curl', side_effect=raises_filenotfound),
            pytest.raises(OdooCLIError, match=r'(?i)curl'),
        ):
            odoo_http.restore_database('backup.zip')
