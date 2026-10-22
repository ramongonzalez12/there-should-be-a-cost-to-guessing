"""Missing migration inputs must never turn into plausible empty ledgers."""
import sqlite3
from pathlib import Path

import pytest

from belowzero.existing import connect_existing


@pytest.mark.parametrize("uri", [False, True])
def test_missing_ledger_is_not_created(tmp_path, uri):
    path = tmp_path / "ledger.sqlite"
    argument = path.as_uri() + "?mode=ro" if uri else path
    with pytest.raises(FileNotFoundError, match="refusing to create"):
        connect_existing(argument, uri=uri)
    assert not path.exists()


def test_existing_ledger_retains_data_and_readonly_mode(tmp_path):
    path = tmp_path / "ledger # 1.sqlite"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE calls(charged REAL)")
        db.execute("INSERT INTO calls VALUES (12.34)")
    with connect_existing(path.as_uri() + "?mode=ro", uri=True) as db:
        assert db.execute("SELECT sum(charged) FROM calls").fetchone() == (12.34,)
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            db.execute("DELETE FROM calls")


def test_disappearing_ledger_is_not_recreated(tmp_path, monkeypatch):
    path = tmp_path / "ledger.sqlite"
    sqlite3.connect(path).close()
    original = Path.is_file

    def disappeared(self):
        result = original(self)
        if self == path:
            self.unlink()
        return result

    monkeypatch.setattr(Path, "is_file", disappeared)
    with pytest.raises(sqlite3.OperationalError):
        connect_existing(path)
    assert not path.exists()
