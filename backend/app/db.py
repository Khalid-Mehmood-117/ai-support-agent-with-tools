"""SQLite connection helper and schema for the store database."""

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS customers (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS products (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    category TEXT NOT NULL,
    price REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS orders (
    id TEXT PRIMARY KEY,
    customer_id INTEGER NOT NULL REFERENCES customers(id),
    status TEXT NOT NULL
        CHECK (status IN ('processing', 'shipped', 'delivered', 'refunded', 'cancelled')),
    ordered_at TEXT NOT NULL,
    shipped_at TEXT,
    delivered_at TEXT,
    carrier TEXT,
    tracking_number TEXT,
    total REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS order_items (
    order_id TEXT NOT NULL REFERENCES orders(id),
    product_id TEXT NOT NULL REFERENCES products(id),
    quantity INTEGER NOT NULL,
    unit_price REAL NOT NULL
);

-- UNIQUE order_id: the database itself refuses a second refund for the same order.
CREATE TABLE IF NOT EXISTS refunds (
    id INTEGER PRIMARY KEY,
    order_id TEXT NOT NULL UNIQUE REFERENCES orders(id),
    amount REAL NOT NULL,
    reason TEXT NOT NULL,
    approved_by TEXT NOT NULL,
    approver_note TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tickets (
    id INTEGER PRIMARY KEY,
    customer_email TEXT NOT NULL,
    order_id TEXT,
    summary TEXT NOT NULL,
    priority TEXT NOT NULL CHECK (priority IN ('low', 'normal', 'high')),
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS email_drafts (
    id INTEGER PRIMARY KEY,
    to_email TEXT NOT NULL,
    subject TEXT NOT NULL,
    body TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS conversations (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS traces (
    conversation_id TEXT NOT NULL REFERENCES conversations(id),
    turn INTEGER NOT NULL,
    trace TEXT NOT NULL,
    PRIMARY KEY (conversation_id, turn)
);
"""


@contextmanager
def connect(path: Path) -> Iterator[sqlite3.Connection]:
    """Open a connection, commit on success, roll back on error, always close."""
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def create_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
