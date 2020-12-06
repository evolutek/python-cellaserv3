import importlib
import pytest

import cellaserv.settings


class TestSettings:
    def fix_monkeypatch(self, monkeypatch):
        # monkeypatching only works if we reload the module
        importlib.reload(cellaserv.settings)

    def teardown_monkeypatch(self, monkeypatch):
        # we have to reload the module to really undo monkeypatching
        monkeypatch.undo()
        importlib.reload(cellaserv.settings)

    def test_env(self, monkeypatch):
        monkeypatch.setenv("CS_HOST", "TESTHOST")
        monkeypatch.setenv("CS_PORT", "1243")
        monkeypatch.setenv("CS_DEBUG", "42")

        self.fix_monkeypatch(monkeypatch)
        assert "TESTHOST" == cellaserv.settings.HOST
        assert 1243 == cellaserv.settings.PORT
        assert 42 == cellaserv.settings.DEBUG
        self.teardown_monkeypatch(monkeypatch)

    @pytest.mark.asyncio
    async def test_get_connection(self):
        assert (
            await cellaserv.settings.get_connection()
        ), "Could not connect to cellaserv"
