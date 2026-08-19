from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")
ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "desk.db"


def now_iso() -> str:
    return datetime.now(KST).replace(microsecond=0).isoformat()


def today_kst() -> str:
    return datetime.now(KST).date().isoformat()


def month_key() -> str:
    return datetime.now(KST).strftime("%Y-%m")


def connect() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def db():
    conn = connect()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with db() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS holdings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticker TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL,
                qty REAL NOT NULL,
                avg_price REAL NOT NULL,
                memo TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS journal (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                body TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS briefs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                kind TEXT NOT NULL,
                day TEXT NOT NULL,
                created_at TEXT NOT NULL,
                payload TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_briefs_day_kind ON briefs(day, kind);
            """
        )
        defaults = {
            "cash": "0",
            "month_key": month_key(),
            "month_start_equity": "",
            "max_names": "6",
        }
        for key, value in defaults.items():
            conn.execute(
                "INSERT OR IGNORE INTO settings(key, value) VALUES (?, ?)",
                (key, value),
            )


def get_setting(key: str, default: str = "") -> str:
    with db() as conn:
        row = conn.execute(
            "SELECT value FROM settings WHERE key = ?", (key,)
        ).fetchone()
        return row["value"] if row else default


def set_setting(key: str, value: str) -> None:
    with db() as conn:
        conn.execute(
            "INSERT INTO settings(key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )


def list_holdings() -> list[dict]:
    with db() as conn:
        rows = conn.execute(
            "SELECT * FROM holdings ORDER BY id ASC"
        ).fetchall()
        return [dict(r) for r in rows]


def upsert_holding(
    ticker: str, name: str, qty: float, avg_price: float, memo: str = ""
) -> dict:
    ticker = ticker.strip().zfill(6)
    with db() as conn:
        existing = conn.execute(
            "SELECT id FROM holdings WHERE ticker = ?", (ticker,)
        ).fetchone()
        if existing:
            conn.execute(
                """
                UPDATE holdings
                SET name = ?, qty = ?, avg_price = ?, memo = ?
                WHERE ticker = ?
                """,
                (name, qty, avg_price, memo, ticker),
            )
        else:
            conn.execute(
                """
                INSERT INTO holdings(ticker, name, qty, avg_price, memo, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (ticker, name, qty, avg_price, memo, now_iso()),
            )
        row = conn.execute(
            "SELECT * FROM holdings WHERE ticker = ?", (ticker,)
        ).fetchone()
        return dict(row)


def delete_holding(holding_id: int) -> None:
    with db() as conn:
        conn.execute("DELETE FROM holdings WHERE id = ?", (holding_id,))


def add_journal(body: str) -> dict:
    with db() as conn:
        cur = conn.execute(
            "INSERT INTO journal(body, created_at) VALUES (?, ?)",
            (body.strip(), now_iso()),
        )
        row = conn.execute(
            "SELECT * FROM journal WHERE id = ?", (cur.lastrowid,)
        ).fetchone()
        return dict(row)


def list_journal(limit: int = 50) -> list[dict]:
    with db() as conn:
        rows = conn.execute(
            "SELECT * FROM journal ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]


def save_brief(kind: str, payload: str) -> dict:
    with db() as conn:
        cur = conn.execute(
            """
            INSERT INTO briefs(kind, day, created_at, payload)
            VALUES (?, ?, ?, ?)
            """,
            (kind, today_kst(), now_iso(), payload),
        )
        row = conn.execute(
            "SELECT id, kind, day, created_at FROM briefs WHERE id = ?",
            (cur.lastrowid,),
        ).fetchone()
        return dict(row)


def latest_brief(kind: str, day: str | None = None) -> dict | None:
    day = day or today_kst()
    with db() as conn:
        row = conn.execute(
            """
            SELECT * FROM briefs
            WHERE kind = ? AND day = ?
            ORDER BY id DESC LIMIT 1
            """,
            (kind, day),
        ).fetchone()
        return dict(row) if row else None
