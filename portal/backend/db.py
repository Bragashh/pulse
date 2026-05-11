"""
Database module for Pulse v1.5.1.

Wraps SQLite with safe helpers for monitored services and (eventually)
deployment audit logs. Schema is created lazily on first connection so
the app works regardless of how it's launched (tests, dev, production).

Environment variables:
  PULSE_DB_PATH — path to the SQLite file (default: /tmp/pulse.db)
"""

import os
import sqlite3
from contextlib import contextmanager


DB_PATH = os.environ.get("PULSE_DB_PATH", "/tmp/pulse.db")


SCHEMA = """
CREATE TABLE IF NOT EXISTS monitored_services (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    url TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    deleted_at TIMESTAMP
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_monitored_services_active_name
    ON monitored_services(name) WHERE deleted_at IS NULL;
"""


@contextmanager
def get_connection():
    """
    Yield a SQLite connection with foreign keys enabled and row-as-dict access.
    Commits on success, rolls back on exception.
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        _ensure_schema(conn)
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _ensure_schema(conn):
    """Run the schema DDL. Idempotent thanks to IF NOT EXISTS."""
    conn.executescript(SCHEMA)


# --- Monitored services ---

def list_monitored_services():
    """Return all non-deleted services, ordered by id."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT id, name, url, created_at FROM monitored_services "
            "WHERE deleted_at IS NULL ORDER BY id"
        ).fetchall()
        return [dict(row) for row in rows]


def add_monitored_service(name: str, url: str) -> int:
    """Insert a new service. Returns the new row id. Raises IntegrityError on duplicate name."""
    with get_connection() as conn:
        cursor = conn.execute(
            "INSERT INTO monitored_services (name, url) VALUES (?, ?)",
            (name, url),
        )
        return cursor.lastrowid


def soft_delete_monitored_service(service_id: int) -> bool:
    """Mark a service as deleted (preserves history). Returns True if a row was updated."""
    with get_connection() as conn:
        cursor = conn.execute(
            "UPDATE monitored_services SET deleted_at = CURRENT_TIMESTAMP "
            "WHERE id = ? AND deleted_at IS NULL",
            (service_id,),
        )
        return cursor.rowcount > 0


def restore_monitored_service(service_id: int) -> bool:
    """Un-delete a previously soft-deleted service. Returns True if a row was updated."""
    with get_connection() as conn:
        cursor = conn.execute(
            "UPDATE monitored_services SET deleted_at = NULL "
            "WHERE id = ? AND deleted_at IS NOT NULL",
            (service_id,),
        )
        return cursor.rowcount > 0