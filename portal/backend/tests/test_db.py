"""
Tests for the database module.

Each test gets a fresh database file via the PULSE_DB_PATH env var, so they
don't interfere with each other or with the running app's DB.
"""

import os
import tempfile
import importlib
import sqlite3
import pytest


@pytest.fixture
def fresh_db(monkeypatch):
    """
    Yield a db module pointed at a fresh, temporary SQLite file.

    monkeypatch sets PULSE_DB_PATH for the duration of the test, then
    restores it. importlib.reload re-reads the env var so the module
    actually picks up the new path.
    """
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.unlink(path)  # SQLite will create it; we just want a unique name

    monkeypatch.setenv("PULSE_DB_PATH", path)

    import db as db_module
    importlib.reload(db_module)

    yield db_module

    if os.path.exists(path):
        os.unlink(path)


def test_list_returns_empty_for_fresh_db(fresh_db):
    """A new DB has no services."""
    assert fresh_db.list_monitored_services() == []


def test_add_then_list_returns_the_service(fresh_db):
    """Added services show up in the list."""
    service_id = fresh_db.add_monitored_service("MyService", "https://example.com")
    services = fresh_db.list_monitored_services()
    assert len(services) == 1
    assert services[0]["id"] == service_id
    assert services[0]["name"] == "MyService"
    assert services[0]["url"] == "https://example.com"


def test_add_duplicate_name_raises_integrity_error(fresh_db):
    """Names must be unique among non-deleted services."""
    fresh_db.add_monitored_service("Dup", "https://a.com")
    with pytest.raises(sqlite3.IntegrityError):
        fresh_db.add_monitored_service("Dup", "https://b.com")


def test_soft_delete_removes_from_list(fresh_db):
    """Soft-deleted services no longer appear in list."""
    service_id = fresh_db.add_monitored_service("ToDelete", "https://example.com")
    assert fresh_db.soft_delete_monitored_service(service_id) is True
    assert fresh_db.list_monitored_services() == []


def test_soft_delete_nonexistent_returns_false(fresh_db):
    """Deleting a non-existent id returns False, not an error."""
    assert fresh_db.soft_delete_monitored_service(99999) is False


def test_can_recreate_after_soft_delete(fresh_db):
    """After soft-deleting, the same name can be added again."""
    fresh_db.add_monitored_service("Recyclable", "https://a.com")
    fresh_db.soft_delete_monitored_service(1)
    new_id = fresh_db.add_monitored_service("Recyclable", "https://b.com")
    assert new_id == 2  # auto-increment, new row


def test_restore_brings_service_back(fresh_db):
    """Soft-deleted services can be restored."""
    service_id = fresh_db.add_monitored_service("Comeback", "https://example.com")
    fresh_db.soft_delete_monitored_service(service_id)
    assert fresh_db.restore_monitored_service(service_id) is True
    services = fresh_db.list_monitored_services()
    assert len(services) == 1


def test_restore_nondeleted_returns_false(fresh_db):
    """Can't restore a service that isn't deleted."""
    service_id = fresh_db.add_monitored_service("Alive", "https://example.com")
    assert fresh_db.restore_monitored_service(service_id) is False