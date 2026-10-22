"""SQLite storage. One table, raw responses preserved verbatim.

Generation and scoring are separated on purpose: the announced contract has
to vary at generation time, but every penalty value, threshold and gate is
applied afterwards in SQL. Run inference once, sweep the parameters forever.
"""

from __future__ import annotations

import hashlib
import os
import sqlite3

DB = os.environ.get("BELOWZERO_DB", "belowzero.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS answers (
  key           TEXT PRIMARY KEY,   -- hash(model, contract, item) => resumable
  benchmark     TEXT, item_id TEXT, kind TEXT,
  model         TEXT, contract TEXT, t REAL,
  question      TEXT, reference TEXT,
  raw           TEXT,               -- full unedited model output
  answer        TEXT,               -- parsed ANSWER field
  confidence    REAL,               -- parsed CONFIDENCE, 0-1
  abstained     INTEGER,            -- explicit "I DON'T KNOW", not a parse failure
  parse_failure INTEGER,
  violated      INTEGER,            -- behaviour track only
  verdict       TEXT,               -- CORRECT / INCORRECT / NOT_ATTEMPTED, set by `grade`
  in_tokens     INTEGER, out_tokens INTEGER, cost_usd REAL,
  latency_s     REAL, error TEXT, ts REAL
);
CREATE INDEX IF NOT EXISTS ix_mc ON answers(model, contract);

-- The answer table remains compact and backwards compatible.  Request and
-- routing provenance lives beside it so a parity claim can be audited without
-- reconstructing what OpenRouter may have done from account-level logs.
CREATE TABLE IF NOT EXISTS call_meta (
  key                TEXT PRIMARY KEY REFERENCES answers(key),
  rep                INTEGER,
  request_json       TEXT,
  response_id        TEXT,
  provider           TEXT,
  upstream_model     TEXT,
  system_fingerprint TEXT,
  finish_reason      TEXT,
  reasoning_tokens   INTEGER,
  reported_cost_usd  REAL
);

-- Every dispatch is append-only here. ``answers`` remains the convenient
-- latest-state table, but an explicitly acknowledged retry must never erase
-- evidence that the prior paid outcome was ambiguous or terminal.
CREATE TABLE IF NOT EXISTS call_attempts (
  attempt_id          INTEGER PRIMARY KEY AUTOINCREMENT,
  key                 TEXT,
  ts                  REAL,
  raw                 TEXT,
  error               TEXT,
  request_json        TEXT,
  response_id         TEXT,
  provider            TEXT,
  upstream_model      TEXT,
  system_fingerprint  TEXT,
  finish_reason       TEXT,
  reasoning_tokens    INTEGER,
  reported_cost_usd   REAL
);
CREATE INDEX IF NOT EXISTS ix_attempt_key ON call_attempts(key, attempt_id);
"""


def db(path: str | None = None):
    con = sqlite3.connect(path or DB, timeout=60)
    con.executescript(SCHEMA)
    # Repositories created before the attempt ledger still have one preserved
    # latest response per key. Seed that as the historical first attempt before
    # any future explicit retry can replace the convenience row.
    con.execute(
        "INSERT INTO call_attempts "
        "(key, ts, raw, error, request_json, response_id, provider, "
        "upstream_model, system_fingerprint, finish_reason, reasoning_tokens, "
        "reported_cost_usd) "
        "SELECT a.key, a.ts, a.raw, a.error, m.request_json, m.response_id, "
        "m.provider, m.upstream_model, m.system_fingerprint, m.finish_reason, "
        "m.reasoning_tokens, m.reported_cost_usd "
        "FROM answers a LEFT JOIN call_meta m ON m.key=a.key "
        "WHERE NOT EXISTS (SELECT 1 FROM call_attempts x WHERE x.key=a.key)"
    )
    con.commit()
    return con


def key_of(model: str, contract: str, item_id: str, rep: int = 0) -> str:
    return hashlib.sha1(f"{model}|{contract}|{item_id}|{rep}".encode()).hexdigest()
