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
from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)

DEFAULT_SQLITE_PATH = os.environ.get("DB_PATH", "data/submissions.db")

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
        _engine = create_engine(url, pool_pre_ping=True, future=True)
    else:
        path = DEFAULT_SQLITE_PATH
        directory = os.path.dirname(path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        _engine = create_engine(
            f"sqlite:///{path}",
            future=True,
            connect_args={"check_same_thread": False},
        )

    metadata.create_all(_engine)
    _add_missing_columns(_engine)
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

    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(submissions.insert().values(**row))
    return submission_id


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
