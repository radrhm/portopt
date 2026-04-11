"""SQLite persistence layer for PortOpt portfolios."""

import sqlite3
import json
import os
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "portopt.db")

# Vercel serverless functions have a read-only filesystem except for /tmp
if os.environ.get("VERCEL_ENV") or os.environ.get("VERCEL"):
    DB_PATH = "/tmp/portopt.db"


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    conn = get_conn()
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS portfolios (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        name        TEXT NOT NULL DEFAULT 'Untitled',
        created_at  TEXT NOT NULL DEFAULT (datetime('now')),
        updated_at  TEXT NOT NULL DEFAULT (datetime('now')),
        settings    TEXT NOT NULL DEFAULT '{}',
        tickers     TEXT NOT NULL DEFAULT '{}',
        overrides   TEXT NOT NULL DEFAULT '{}',
        bl_views    TEXT NOT NULL DEFAULT '{}',
        custom_weights TEXT,
        results     TEXT,
        is_custom   INTEGER NOT NULL DEFAULT 0
    );
    """)
    conn.commit()
    conn.close()


# ── CRUD ──────────────────────────────────────────────────────────────────────

def list_portfolios():
    conn = get_conn()
    rows = conn.execute(
        "SELECT id, name, created_at, updated_at, is_custom FROM portfolios ORDER BY updated_at DESC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_portfolio(pid):
    conn = get_conn()
    row = conn.execute("SELECT * FROM portfolios WHERE id=?", (pid,)).fetchone()
    conn.close()
    if not row:
        return None
    d = dict(row)
    for k in ("settings", "tickers", "overrides", "bl_views", "custom_weights", "results"):
        if d.get(k):
            try:
                d[k] = json.loads(d[k])
            except (json.JSONDecodeError, TypeError):
                d[k] = {} if k != "results" else None
        else:
            d[k] = {} if k not in ("results", "custom_weights") else None
    return d


def save_portfolio(data):
    """Insert or update. If data has 'id', update; otherwise insert. Returns id."""
    conn = get_conn()
    now = datetime.utcnow().isoformat()
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

    if pid:
        sets = ", ".join(f"{k}=?" for k in fields)
        conn.execute(f"UPDATE portfolios SET {sets} WHERE id=?", (*fields.values(), pid))
    else:
        fields["created_at"] = now
        cols = ", ".join(fields.keys())
        qs = ", ".join("?" * len(fields))
        cur = conn.execute(f"INSERT INTO portfolios ({cols}) VALUES ({qs})", tuple(fields.values()))
        pid = cur.lastrowid

    conn.commit()
    conn.close()
    return pid


def delete_portfolio(pid):
    conn = get_conn()
    conn.execute("DELETE FROM portfolios WHERE id=?", (pid,))
    conn.commit()
    conn.close()


# Initialize on import
init_db()
