"""Open retained databases without ever creating a replacement for missing data."""

import sqlite3
from pathlib import Path
from urllib.parse import parse_qsl, unquote, urlencode, urlsplit


def connect_existing(database, *args, **kwargs):
    """Require a real file and use SQLite's non-creating mode as a second guard.

    The existence check gives an actionable error. ``mode=rw`` also closes the
    check/open race: if a migration removes the file between those operations,
    SQLite raises instead of silently replacing paid history with an empty DB.
    Read-only callers retain their ``mode=ro`` restriction.
    """
    value = str(database)
    options = {}
    if kwargs.get("uri") and value.startswith("file:"):
        parsed = urlsplit(value)
        if parsed.netloc not in {"", "localhost"}:
            raise ValueError("Retained database must be a local file")
        path = Path(unquote(parsed.path))
        options = dict(parse_qsl(parsed.query))
    else:
        path = Path(database)
    if not path.is_file():
        raise FileNotFoundError(f"Retained database is missing; refusing to create it: {path}")
    mode = options.get("mode", "rw")
    if mode not in {"ro", "rw"}:
        raise ValueError("Retained databases require SQLite mode=ro or mode=rw")
    options["mode"] = mode
    kwargs["uri"] = True
    return sqlite3.connect(path.resolve().as_uri() + "?" + urlencode(options), *args, **kwargs)
