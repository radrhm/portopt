"""Persistence layer — PostgreSQL (Supabase) in production, SQLite locally.

Automatically picks the right backend:
  - DATABASE_URL env var set  →  PostgreSQL (Vercel / Supabase)
  - No DATABASE_URL           →  SQLite file next to this module (local dev)
"""

import json
import logging
import os
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

_DATABASE_URL = os.environ.get("DATABASE_URL", "")
_USE_PG = bool(_DATABASE_URL)


def _utcnow() -> str:
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat()


# ── Connection helpers ───────────────────────────────────────────────────────

def _pg_conn():
    import psycopg2
    import psycopg2.extras
    conn = psycopg2.connect(_DATABASE_URL)
    return conn


def _sqlite_conn():
    import sqlite3
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "portopt.db")
    try:
        with open(path, "a"):
            pass
    except OSError:
        path = "/tmp/portopt.db"
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def get_conn():
    return _pg_conn() if _USE_PG else _sqlite_conn()


# ── Migrations ───────────────────────────────────────────────────────────────

_PG_MIGRATIONS = [
    (1, [
        """CREATE TABLE IF NOT EXISTS schema_version (
               version    INTEGER PRIMARY KEY,
               applied_at TEXT NOT NULL
           )""",
        """CREATE TABLE IF NOT EXISTS portfolios (
               id             SERIAL PRIMARY KEY,
               name           TEXT NOT NULL DEFAULT 'Untitled',
               created_at     TEXT NOT NULL,
               updated_at     TEXT NOT NULL,
               settings       TEXT NOT NULL DEFAULT '{}',
               tickers        TEXT NOT NULL DEFAULT '{}',
               overrides      TEXT NOT NULL DEFAULT '{}',
               bl_views       TEXT NOT NULL DEFAULT '{}',
               custom_weights TEXT,
               results        TEXT,
               is_custom      INTEGER NOT NULL DEFAULT 0
           )""",
        """CREATE TABLE IF NOT EXISTS valuation_lists (
               id         SERIAL PRIMARY KEY,
               name       TEXT NOT NULL DEFAULT 'New List',
               created_at TEXT NOT NULL,
               updated_at TEXT NOT NULL,
               tickers    TEXT NOT NULL DEFAULT '[]'
           )""",
    ]),
]

_SQLITE_MIGRATIONS = [
    (1, """
        CREATE TABLE IF NOT EXISTS schema_version (
            version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS portfolios (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            name           TEXT NOT NULL DEFAULT 'Untitled',
            created_at     TEXT NOT NULL,
            updated_at     TEXT NOT NULL,
            settings       TEXT NOT NULL DEFAULT '{}',
            tickers        TEXT NOT NULL DEFAULT '{}',
            overrides      TEXT NOT NULL DEFAULT '{}',
            bl_views       TEXT NOT NULL DEFAULT '{}',
            custom_weights TEXT,
            results        TEXT,
            is_custom      INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS valuation_lists (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            name       TEXT NOT NULL DEFAULT 'New List',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            tickers    TEXT NOT NULL DEFAULT '[]'
        );
    """),
]


def init_db() -> None:
    """Create tables if they don't exist. Safe to call on every cold start."""
    try:
        if _USE_PG:
            _init_pg()
        else:
            _init_sqlite()
    except Exception:
        logger.exception("init_db failed — persistence unavailable")


def _init_pg() -> None:
    import psycopg2
    conn = _pg_conn()
    cur = conn.cursor()
    # Ensure schema_version exists first
    cur.execute("""CREATE TABLE IF NOT EXISTS schema_version (
                       version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL
                   )""")
    cur.execute("SELECT COALESCE(MAX(version), 0) FROM schema_version")
    current = cur.fetchone()[0]
    for version, stmts in _PG_MIGRATIONS:
        if version > current:
            for sql in stmts:
                cur.execute(sql)
            cur.execute(
                "INSERT INTO schema_version (version, applied_at) VALUES (%s, %s)",
                (version, _utcnow()),
            )
            logger.info("Applied PG migration v%d", version)
    conn.commit()
    cur.close()
    conn.close()


def _init_sqlite() -> None:
    import sqlite3
    conn = _sqlite_conn()
    conn.execute("""CREATE TABLE IF NOT EXISTS schema_version (
                        version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL
                    )""")
    current = conn.execute(
        "SELECT COALESCE(MAX(version), 0) FROM schema_version"
    ).fetchone()[0]
    for version, script in _SQLITE_MIGRATIONS:
        if version > current:
            conn.executescript(script)
            conn.execute(
                "INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
                (version, _utcnow()),
            )
            logger.info("Applied SQLite migration v%d", version)
    conn.commit()
    conn.close()


# ── JSON helpers ─────────────────────────────────────────────────────────────

_JSON_FIELDS = ("settings", "tickers", "overrides", "bl_views", "custom_weights", "results")


def _deserialize(d: dict) -> dict:
    for k in _JSON_FIELDS:
        if d.get(k):
            try:
                d[k] = json.loads(d[k])
            except (json.JSONDecodeError, TypeError):
                d[k] = {} if k not in ("results", "custom_weights") else None
        else:
            d[k] = {} if k not in ("results", "custom_weights") else None
    return d


# ── Portfolio CRUD ───────────────────────────────────────────────────────────

def list_portfolios() -> list[dict]:
    conn = get_conn()
    if _USE_PG:
        import psycopg2.extras
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT * FROM portfolios ORDER BY updated_at DESC")
        rows = [dict(r) for r in cur.fetchall()]
        cur.close()
    else:
        rows = [dict(r) for r in conn.execute(
            "SELECT * FROM portfolios ORDER BY updated_at DESC"
        ).fetchall()]
    conn.close()
    return [_deserialize(r) for r in rows]


def get_portfolio(pid: int) -> dict | None:
    conn = get_conn()
    if _USE_PG:
        import psycopg2.extras
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT * FROM portfolios WHERE id=%s", (pid,))
        row = cur.fetchone()
        cur.close()
        row = dict(row) if row else None
    else:
        row = conn.execute("SELECT * FROM portfolios WHERE id=?", (pid,)).fetchone()
        row = dict(row) if row else None
    conn.close()
    return _deserialize(row) if row else None


def save_portfolio(data: dict) -> int:
    conn = get_conn()
    now = _utcnow()
    pid = data.get("id")

    fields = {
        "name":           data.get("name", "Untitled"),
        "updated_at":     now,
        "settings":       json.dumps(data.get("settings", {})),
        "tickers":        json.dumps(data.get("tickers", {})),
        "overrides":      json.dumps(data.get("overrides", {})),
        "bl_views":       json.dumps(data.get("bl_views", {})),
        "custom_weights": json.dumps(data.get("custom_weights")) if data.get("custom_weights") else None,
        "results":        json.dumps(data.get("results")) if data.get("results") else None,
        "is_custom":      1 if data.get("is_custom") else 0,
    }

    if _USE_PG:
        ph = "%s"
        ret = " RETURNING id"
    else:
        ph = "?"
        ret = ""

    if pid:
        sets = ", ".join(f"{k}={ph}" for k in fields)
        sql = f"UPDATE portfolios SET {sets} WHERE id={ph}{ret}"
        params = (*fields.values(), pid)
        if _USE_PG:
            cur = conn.cursor()
            cur.execute(sql, params)
            row = cur.fetchone()
            pid = row[0] if row else pid
            cur.close()
        else:
            conn.execute(sql, params)
    else:
        fields["created_at"] = now
        cols = ", ".join(fields.keys())
        phs = ", ".join([ph] * len(fields))
        sql = f"INSERT INTO portfolios ({cols}) VALUES ({phs}){ret}"
        if _USE_PG:
            cur = conn.cursor()
            cur.execute(sql, tuple(fields.values()))
            pid = cur.fetchone()[0]
            cur.close()
        else:
            cur = conn.execute(sql, tuple(fields.values()))
            pid = cur.lastrowid

    conn.commit()
    conn.close()
    return pid


def delete_portfolio(pid: int) -> None:
    conn = get_conn()
    if _USE_PG:
        cur = conn.cursor()
        cur.execute("DELETE FROM portfolios WHERE id=%s", (pid,))
        cur.close()
    else:
        conn.execute("DELETE FROM portfolios WHERE id=?", (pid,))
    conn.commit()
    conn.close()


# ── Valuation lists CRUD ─────────────────────────────────────────────────────

def list_val_lists() -> list[dict]:
    conn = get_conn()
    if _USE_PG:
        import psycopg2.extras
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(
            "SELECT id, name, created_at, updated_at, tickers "
            "FROM valuation_lists ORDER BY updated_at DESC"
        )
        rows = [dict(r) for r in cur.fetchall()]
        cur.close()
    else:
        rows = [dict(r) for r in conn.execute(
            "SELECT id, name, created_at, updated_at, tickers "
            "FROM valuation_lists ORDER BY updated_at DESC"
        ).fetchall()]
    conn.close()
    result = []
    for d in rows:
        try:
            d["tickers"] = json.loads(d["tickers"]) if d["tickers"] else []
        except (json.JSONDecodeError, TypeError):
            d["tickers"] = []
        result.append(d)
    return result


def get_val_list(lid: int) -> dict | None:
    conn = get_conn()
    if _USE_PG:
        import psycopg2.extras
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT * FROM valuation_lists WHERE id=%s", (lid,))
        row = cur.fetchone()
        cur.close()
        row = dict(row) if row else None
    else:
        row = conn.execute("SELECT * FROM valuation_lists WHERE id=?", (lid,)).fetchone()
        row = dict(row) if row else None
    conn.close()
    if not row:
        return None
    try:
        row["tickers"] = json.loads(row["tickers"]) if row["tickers"] else []
    except (json.JSONDecodeError, TypeError):
        row["tickers"] = []
    return row


def save_val_list(data: dict) -> int:
    conn = get_conn()
    now = _utcnow()
    lid = data.get("id")
    ph = "%s" if _USE_PG else "?"

    fields = {
        "name":       data.get("name", "New List"),
        "updated_at": now,
        "tickers":    json.dumps(data.get("tickers", [])),
    }

    if lid:
        sets = ", ".join(f"{k}={ph}" for k in fields)
        ret = " RETURNING id" if _USE_PG else ""
        sql = f"UPDATE valuation_lists SET {sets} WHERE id={ph}{ret}"
        params = (*fields.values(), lid)
        if _USE_PG:
            cur = conn.cursor()
            cur.execute(sql, params)
            row = cur.fetchone()
            lid = row[0] if row else lid
            cur.close()
        else:
            conn.execute(sql, params)
    else:
        fields["created_at"] = now
        cols = ", ".join(fields.keys())
        phs = ", ".join([ph] * len(fields))
        ret = " RETURNING id" if _USE_PG else ""
        sql = f"INSERT INTO valuation_lists ({cols}) VALUES ({phs}){ret}"
        if _USE_PG:
            cur = conn.cursor()
            cur.execute(sql, tuple(fields.values()))
            lid = cur.fetchone()[0]
            cur.close()
        else:
            cur = conn.execute(sql, tuple(fields.values()))
            lid = cur.lastrowid

    conn.commit()
    conn.close()
    return lid


def delete_val_list(lid: int) -> None:
    conn = get_conn()
    if _USE_PG:
        cur = conn.cursor()
        cur.execute("DELETE FROM valuation_lists WHERE id=%s", (lid,))
        cur.close()
    else:
        conn.execute("DELETE FROM valuation_lists WHERE id=?", (lid,))
    conn.commit()
    conn.close()


# Initialize on import
init_db()
