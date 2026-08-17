"""Persistence layer.

Uses SQLAlchemy Core so the same code runs against SQLite (default, zero
config) or Postgres (set ``DATABASE_URL``). Hosted Streamlit containers have
ephemeral disks, so point ``DATABASE_URL`` at a managed Postgres if you need
submissions to survive a restart.
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    Float,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    create_engine,
    delete,
    func,
    inspect,
    select,
    text,
)
from sqlalchemy.engine import Engine, make_url

logger = logging.getLogger(__name__)

DEFAULT_SQLITE_PATH = os.environ.get("DB_PATH", "data/submissions.db")

class StorageError(RuntimeError):
    """A submission could not be written to the database.

    ``queued`` says whether it was parked in the fallback file, and so
    whether it can still be recovered.
    """

    def __init__(self, message: str, queued: bool) -> None:
        super().__init__(message)
        self.queued = queued


metadata = MetaData()

submissions = Table(
    "submissions",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("created_at", DateTime(timezone=True), nullable=False, index=True),
    # participant details
    Column("full_name", String(200)),
    Column("student_id", String(60), index=True),
    Column("email", String(200), index=True),
    Column("age", Integer),
    Column("gender", String(50)),
    Column("occupation", String(200)),
    Column("notes", Text),
    # headline scores, denormalised so the admin table and filters stay fast
    Column("asrs_part_a_count", Integer),
    Column("asrs_screen_positive", String(5)),
    Column("asrs_part_b_count", Integer),
    Column("asrs_total_raw", Integer),
    Column("pss_total", Integer),
    Column("pss_band", String(60)),
    Column("who5_raw", Integer),
    Column("who5_percentage", Integer),
    Column("who5_band", String(60)),
    Column("rmeq_total", Integer),
    Column("rmeq_band", String(60)),
    Column("hsps_total", Integer),
    Column("hsps_mean_item", Float),
    Column("hsps_band", String(60)),
    # everything else
    Column("responses", JSON),
    Column("scores", JSON),
    Column("duration_seconds", Integer),
)


_engine: Engine | None = None


def get_engine() -> Engine:
    """Return a process-wide engine, creating tables on first use."""
    global _engine
    if _engine is not None:
        return _engine

    url = os.environ.get("DATABASE_URL", "").strip()
    if url:
        # SQLAlchemy needs the postgresql+psycopg2 form
        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql://", 1)
        # Fail fast rather than hanging a page load for the TCP default when the
        # host is unreachable (a wrong or IPv6-only host, or a paused database).
        engine = create_engine(
            url,
            pool_pre_ping=True,
            future=True,
            connect_args={"connect_timeout": 10},
        )
    else:
        path = DEFAULT_SQLITE_PATH
        directory = os.path.dirname(path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        engine = create_engine(
            f"sqlite:///{path}",
            future=True,
            connect_args={"check_same_thread": False},
        )

    # Publish to the module global only once the schema is actually in place.
    # Assigning earlier means a create_all that fails to connect still leaves a
    # cached engine behind, and the next call short-circuits on it and skips
    # schema setup entirely - so the app looks healthy and only fails later, at
    # the point someone tries to save.
    metadata.create_all(engine)
    _add_missing_columns(engine)
    _engine = engine
    return _engine


# SQLAlchemy's create_all only creates missing tables, never missing columns, so
# a table created by an older version of this app keeps its old shape. Both
# SQLite and Postgres accept a plain ADD COLUMN, which is all this schema needs;
# letting the dialect compile the type keeps JSON and timestamp columns correct.
def _add_missing_columns(engine: Engine) -> None:
    inspector = inspect(engine)
    if not inspector.has_table(submissions.name):
        return
    existing = {col["name"] for col in inspector.get_columns(submissions.name)}
    for column in submissions.columns:
        if column.name in existing:
            continue
        sql_type = column.type.compile(dialect=engine.dialect)
        with engine.begin() as conn:
            conn.execute(
                text(
                    f"ALTER TABLE {submissions.name} "
                    f'ADD COLUMN "{column.name}" {sql_type}'
                )
            )
        logger.info("added missing column %s", column.name)


def backend_name() -> str:
    url = os.environ.get("DATABASE_URL", "").strip()
    return "PostgreSQL" if url else f"SQLite ({DEFAULT_SQLITE_PATH})"


def describe_target() -> dict[str, Any]:
    """Sanitised description of the configured database.

    Never includes the password: this is rendered on an error page that
    anyone hitting the app could see.
    """
    raw = os.environ.get("DATABASE_URL", "").strip()
    if not raw:
        return {"configured": False}

    if raw.startswith("postgres://"):
        raw = raw.replace("postgres://", "postgresql://", 1)
    try:
        url = make_url(raw)
    except Exception:
        return {"configured": True, "parse_error": True}

    host = url.host or ""
    info: dict[str, Any] = {
        "configured": True,
        "parse_error": False,
        "host": host,
        "port": url.port or 5432,
        "database": url.database,
        "username": url.username,
        "has_password": bool(url.password),
        "driver": url.get_backend_name(),
    }
    # Supabase's direct host is IPv6-only; Streamlit Cloud cannot reach it.
    info["supabase_direct"] = host.startswith("db.") and host.endswith(
        ".supabase.co"
    )
    info["supabase_pooler"] = "pooler.supabase.com" in host
    return info


def check_connection() -> tuple[bool, str]:
    """Try one connection. Returns (ok, sanitised error)."""
    try:
        engine = get_engine()
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True, ""
    except Exception as exc:
        return False, sanitise_error(exc)


def sanitise_error(exc: Exception) -> str:
    """Error text with any password from DATABASE_URL scrubbed out."""
    message = f"{type(exc).__name__}: {exc}"
    raw = os.environ.get("DATABASE_URL", "").strip()
    if raw:
        try:
            password = make_url(
                raw.replace("postgres://", "postgresql://", 1)
            ).password
            if password:
                message = message.replace(password, "***")
        except Exception:
            pass
    return message[:1500]


def is_ephemeral() -> bool:
    """True when submissions sit on a local file rather than a real server.

    Fine locally; on a hosted container it means a restart loses everything.
    """
    return not os.environ.get("DATABASE_URL", "").strip()


def save_submission(
    participant: dict[str, Any],
    responses: dict[str, int],
    results: dict[str, Any],
    duration_seconds: int | None = None,
) -> str:
    """Persist one completed assessment and return its id."""
    from .scoring import flatten_scores

    flat = flatten_scores(results)
    submission_id = str(uuid.uuid4())

    def band(key: str) -> str | None:
        return results[key].band.label if key in results else None

    def metric(key: str, name: str) -> Any:
        return results[key].metrics.get(name) if key in results else None

    row = {
        "id": submission_id,
        "created_at": datetime.now(timezone.utc),
        "full_name": participant.get("full_name"),
        "student_id": participant.get("student_id"),
        "email": participant.get("email"),
        "age": participant.get("age"),
        "gender": participant.get("gender"),
        "occupation": participant.get("occupation"),
        "notes": participant.get("notes"),
        "asrs_part_a_count": results["asrs"].headline if "asrs" in results else None,
        "asrs_screen_positive": metric("asrs", "part_a_screen_positive"),
        "asrs_part_b_count": metric("asrs", "part_b_shaded_count"),
        "asrs_total_raw": metric("asrs", "total_raw_sum"),
        "pss_total": results["pss"].headline if "pss" in results else None,
        "pss_band": band("pss"),
        "who5_raw": metric("who5", "raw_score"),
        "who5_percentage": results["who5"].headline if "who5" in results else None,
        "who5_band": band("who5"),
        "rmeq_total": results["rmeq"].headline if "rmeq" in results else None,
        "rmeq_band": band("rmeq"),
        "hsps_total": results["hsps"].headline if "hsps" in results else None,
        "hsps_mean_item": metric("hsps", "mean_item_score"),
        "hsps_band": band("hsps"),
        "responses": responses,
        "scores": json.loads(json.dumps(flat, default=str)),
        "duration_seconds": duration_seconds,
    }

    try:
        engine = get_engine()
        with engine.begin() as conn:
            conn.execute(submissions.insert().values(**row))
    except Exception as exc:
        # The participant has already answered every question; losing the row
        # here is the one outcome worth spending a disk write to avoid.
        queued = queue_failed_submission(row)
        raise StorageError(sanitise_error(exc), queued=queued) from exc
    return submission_id


# --------------------------------------------------------------------------
# Fallback queue
# --------------------------------------------------------------------------
# When the database is unreachable a completed assessment would otherwise be
# lost outright: the participant has answered 65 questions and there is nowhere
# to put them. Rows are appended here instead and imported once the database is
# back. This file is on the container's disk, so it survives a database blip
# but NOT a container restart - it buys recovery time, it is not a substitute
# for a reachable database.
FALLBACK_PATH = os.environ.get("FALLBACK_PATH", "data/pending_submissions.jsonl")


def queue_failed_submission(row: dict[str, Any]) -> bool:
    """Append a submission that could not be saved. Returns True if stored."""
    try:
        directory = os.path.dirname(FALLBACK_PATH)
        if directory:
            os.makedirs(directory, exist_ok=True)
        with open(FALLBACK_PATH, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, default=str) + "\n")
        return True
    except Exception:
        logger.exception("could not write fallback submission")
        return False


def pending_submissions() -> list[dict[str, Any]]:
    if not os.path.exists(FALLBACK_PATH):
        return []
    rows = []
    try:
        with open(FALLBACK_PATH, encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if line:
                    rows.append(json.loads(line))
    except Exception:
        logger.exception("could not read fallback submissions")
    return rows


def import_pending() -> tuple[int, int]:
    """Insert queued submissions. Returns (imported, still_pending)."""
    rows = pending_submissions()
    if not rows:
        return 0, 0

    engine = get_engine()
    remaining: list[dict[str, Any]] = []
    imported = 0
    existing = {r["id"] for r in fetch_all()}

    for row in rows:
        if row.get("id") in existing:
            imported += 1  # already made it in; drop the duplicate
            continue
        try:
            payload = dict(row)
            payload["created_at"] = datetime.fromisoformat(payload["created_at"])
            with engine.begin() as conn:
                conn.execute(submissions.insert().values(**payload))
            imported += 1
        except Exception:
            logger.exception("could not import queued submission")
            remaining.append(row)

    try:
        if remaining:
            with open(FALLBACK_PATH, "w", encoding="utf-8") as handle:
                for row in remaining:
                    handle.write(json.dumps(row, default=str) + "\n")
        elif os.path.exists(FALLBACK_PATH):
            os.remove(FALLBACK_PATH)
    except Exception:
        logger.exception("could not rewrite fallback file")

    return imported, len(remaining)


def fetch_all() -> list[dict[str, Any]]:
    """Every submission, newest first."""
    engine = get_engine()
    with engine.connect() as conn:
        rows = conn.execute(
            select(submissions).order_by(submissions.c.created_at.desc())
        ).mappings().all()
    return [dict(r) for r in rows]


def fetch_one(submission_id: str) -> dict[str, Any] | None:
    engine = get_engine()
    with engine.connect() as conn:
        row = conn.execute(
            select(submissions).where(submissions.c.id == submission_id)
        ).mappings().first()
    return dict(row) if row else None


def count_submissions() -> int:
    engine = get_engine()
    with engine.connect() as conn:
        return int(conn.execute(select(func.count()).select_from(submissions)).scalar_one())


def delete_submission(submission_id: str) -> bool:
    engine = get_engine()
    with engine.begin() as conn:
        result = conn.execute(
            delete(submissions).where(submissions.c.id == submission_id)
        )
    return result.rowcount > 0
