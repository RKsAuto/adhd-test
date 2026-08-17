"""Tests for engine setup and storage behaviour."""

from __future__ import annotations

import importlib
import os

import pytest

from assessment import db as db_module


@pytest.fixture
def db(tmp_path, monkeypatch):
    """A freshly imported db module with no cached engine."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("DB_PATH", str(tmp_path / "test.db"))
    module = importlib.reload(db_module)
    yield module
    module._engine = None


def test_sqlite_engine_creates_schema(db):
    engine = db.get_engine()
    from sqlalchemy import inspect

    assert inspect(engine).has_table("submissions")
    assert db.is_ephemeral() is True


def test_unreachable_database_does_not_cache_a_broken_engine(db, monkeypatch):
    """A failed setup must not leave an engine behind.

    Regression: the global was assigned before create_all ran, so a connection
    failure still cached the engine. The next call short-circuited on it,
    skipped schema setup, and the app only failed later when saving.
    """
    monkeypatch.setenv(
        "DATABASE_URL", "postgresql://u:p@nonexistent.invalid:5432/db"
    )
    db._engine = None

    with pytest.raises(Exception):
        db.get_engine()

    # The important part: nothing cached, so a later call retries properly
    # instead of handing back an engine whose tables were never created.
    assert db._engine is None

    with pytest.raises(Exception):
        db.get_engine()


def test_check_connection_reports_failure_without_raising(db, monkeypatch):
    monkeypatch.setenv(
        "DATABASE_URL", "postgresql://u:secretpw@nonexistent.invalid:5432/db"
    )
    db._engine = None
    ok, message = db.check_connection()
    assert ok is False
    assert message
    assert "secretpw" not in message


def test_describe_target_flags_supabase_direct_host(db, monkeypatch):
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql://postgres:pw@db.abcdefgh.supabase.co:5432/postgres",
    )
    target = db.describe_target()
    assert target["supabase_direct"] is True
    assert target["supabase_pooler"] is False
    assert target["host"] == "db.abcdefgh.supabase.co"


def test_describe_target_accepts_pooler_host(db, monkeypatch):
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql://postgres.abcdefgh:pw@aws-0-ap-south-1.pooler.supabase.com"
        ":5432/postgres",
    )
    target = db.describe_target()
    assert target["supabase_direct"] is False
    assert target["supabase_pooler"] is True


def test_describe_target_never_exposes_the_password(db, monkeypatch):
    monkeypatch.setenv(
        "DATABASE_URL", "postgresql://u:sup3rs3cret@host:5432/db"
    )
    assert "sup3rs3cret" not in repr(db.describe_target())


def test_describe_target_unconfigured(db):
    assert db.describe_target() == {"configured": False}


def test_postgres_scheme_is_normalised(db, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgres://u:p@host:5432/db")
    target = db.describe_target()
    assert target["driver"] == "postgresql"
    assert target["host"] == "host"


def test_save_and_fetch_roundtrip(db):
    from assessment.instruments import INSTRUMENTS
    from assessment.scoring import score_all

    responses = {
        item.id: item.options[0][1]
        for inst in INSTRUMENTS.values()
        for item in inst.items
    }
    results = score_all(responses)
    sid = db.save_submission(
        {"full_name": "Test", "student_id": "S-1", "email": "t@x.com"},
        responses,
        results,
        120,
    )
    row = db.fetch_one(sid)
    assert row["student_id"] == "S-1"
    assert len(row["responses"]) == 65
    assert db.count_submissions() == 1
    assert db.delete_submission(sid) is True
    assert db.count_submissions() == 0
