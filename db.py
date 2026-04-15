"""SQLite persistence layer for PortOpt portfolios."""

import sqlite3
import json
import logging
import os
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "portopt.db")

# Fallback to /tmp if we cannot write to the current directory (Vercel / AWS Lambda)
try:
    with open(DB_PATH, "a"):
        pass
except OSError:
    DB_PATH = "/tmp/portopt.db"


def _utcnow() -> str:
    """Return current UTC time as an ISO string (no tzinfo suffix)."""
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat()


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db() -> None:
    try:
        conn = get_conn()
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS portfolios (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            name           TEXT NOT NULL DEFAULT 'Untitled',
            created_at     TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at     TEXT NOT NULL DEFAULT (datetime('now')),
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
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now')),
            tickers    TEXT NOT NULL DEFAULT '[]'
        );
        """)
        conn.commit()
        conn.close()
    except Exception:
        logger.exception("init_db failed — portfolio persistence unavailable")


# ── CRUD ───────────────────────────────────────────────────────────────────────

def list_portfolios() -> list[dict]:
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM portfolios ORDER BY updated_at DESC"
    ).fetchall()
    conn.close()
    result = []
    for r in rows:
        d = dict(r)
        for k in ("settings", "tickers", "overrides", "bl_views", "custom_weights", "results"):
            if d.get(k):
                try:
                    d[k] = json.loads(d[k])
                except (json.JSONDecodeError, TypeError):
                    d[k] = {} if k != "results" else None
            else:
                d[k] = {} if k not in ("results", "custom_weights") else None
        result.append(d)
    return result


def get_portfolio(pid: int) -> dict | None:
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


def save_portfolio(data: dict) -> int:
    """Insert or update. If data has 'id', update; otherwise insert. Returns id."""
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


def delete_portfolio(pid: int) -> None:
    conn = get_conn()
    conn.execute("DELETE FROM portfolios WHERE id=?", (pid,))
    conn.commit()
    conn.close()


# ── VALUATION LISTS CRUD ───────────────────────────────────────────────────────

def list_val_lists() -> list[dict]:
    conn = get_conn()
    rows = conn.execute(
        "SELECT id, name, created_at, updated_at, tickers FROM valuation_lists ORDER BY updated_at DESC"
    ).fetchall()
    conn.close()
    result = []
    for r in rows:
        d = dict(r)
        try:
            d["tickers"] = json.loads(d["tickers"]) if d["tickers"] else []
        except (json.JSONDecodeError, TypeError):
            d["tickers"] = []
        result.append(d)
    return result


def get_val_list(lid: int) -> dict | None:
    conn = get_conn()
    row = conn.execute("SELECT * FROM valuation_lists WHERE id=?", (lid,)).fetchone()
    conn.close()
    if not row:
        return None
    d = dict(row)
    try:
        d["tickers"] = json.loads(d["tickers"]) if d["tickers"] else []
    except (json.JSONDecodeError, TypeError):
        d["tickers"] = []
    return d


def save_val_list(data: dict) -> int:
    """Insert or update. If data has 'id', update; otherwise insert. Returns id."""
    conn = get_conn()
    now = _utcnow()
    lid = data.get("id")

    fields = {
        "name":       data.get("name", "New List"),
        "updated_at": now,
        "tickers":    json.dumps(data.get("tickers", [])),
    }

    if lid:
        sets = ", ".join(f"{k}=?" for k in fields)
        conn.execute(f"UPDATE valuation_lists SET {sets} WHERE id=?", (*fields.values(), lid))
    else:
        fields["created_at"] = now
        cols = ", ".join(fields.keys())
        qs = ", ".join("?" * len(fields))
        cur = conn.execute(
            f"INSERT INTO valuation_lists ({cols}) VALUES ({qs})", tuple(fields.values())
        )
        lid = cur.lastrowid

    conn.commit()
    conn.close()
    return lid


def delete_val_list(lid: int) -> None:
    conn = get_conn()
    conn.execute("DELETE FROM valuation_lists WHERE id=?", (lid,))
    conn.commit()
    conn.close()


# Initialize on import
init_db()
