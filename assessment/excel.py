"""Combined Excel export for the admin board."""

from __future__ import annotations

import io
from typing import Any

import pandas as pd

from .instruments import INSTRUMENTS, get_item

PARTICIPANT_COLUMNS = [
    ("id", "Submission ID"),
    ("created_at", "Submitted at (UTC)"),
    ("student_id", "Student ID"),
    ("full_name", "Name"),
    ("email", "Email"),
    ("age", "Age"),
    ("gender", "Gender"),
    ("occupation", "Occupation"),
    ("duration_seconds", "Duration (s)"),
    ("notes", "Participant notes"),
]

SCORE_COLUMNS = [
    ("asrs_part_a_sum", "ASRS Part A score (/24)"),
    ("asrs_part_b_sum", "ASRS Part B score (/48)"),
    ("asrs_total_raw", "ASRS total score (/72)"),
    ("asrs_part_a_count", "ASRS Part A shaded count (/6)"),
    ("asrs_screen_positive", "ASRS screen positive"),
    ("asrs_part_b_count", "ASRS Part B shaded count (/12)"),
    ("pss_total", "PSS-10 total (/40)"),
    ("pss_band", "PSS-10 interpretation"),
    ("who5_raw", "WHO-5 raw (/25)"),
    ("who5_percentage", "WHO-5 percentage"),
    ("who5_band", "WHO-5 interpretation"),
    ("rmeq_total", "rMEQ total (4-25)"),
    ("rmeq_band", "rMEQ chronotype"),
    ("hsps_total", "HSPS total (27-189)"),
    ("hsps_mean_item", "HSPS mean item score"),
    ("hsps_band", "HSPS interpretation"),
]


def _naive_utc(value: Any) -> Any:
    """Excel cannot hold a timezone, so store the UTC wall time."""
    if value is None:
        return None
    stamp = pd.to_datetime(value, errors="coerce")
    if pd.isna(stamp):
        return value
    if stamp.tzinfo is not None:
        stamp = stamp.tz_convert("UTC").tz_localize(None)
    return stamp.to_pydatetime()


def _base_frame(rows: list[dict[str, Any]]) -> pd.DataFrame:
    """Participant details + all headline scores, one row per submission."""
    records = []
    for row in rows:
        record: dict[str, Any] = {}
        for key, label in PARTICIPANT_COLUMNS:
            value = row.get(key)
            if key == "created_at":
                value = _naive_utc(value)
            record[label] = value
        for key, label in SCORE_COLUMNS:
            record[label] = row.get(key)
        records.append(record)
    return pd.DataFrame.from_records(records)


def _item_columns(instrument_keys: list[str]) -> list[tuple[str, str]]:
    columns = []
    for key in instrument_keys:
        inst = INSTRUMENTS[key]
        for item in inst.items:
            columns.append((item.id, f"{inst.short_name} Q{item.number}"))
    return columns


def _responses_frame(
    rows: list[dict[str, Any]], instrument_keys: list[str], with_labels: bool
) -> pd.DataFrame:
    """One row per submission, one column per item."""
    columns = _item_columns(instrument_keys)
    records = []
    for row in rows:
        responses = row.get("responses") or {}
        record: dict[str, Any] = {
            "Submission ID": row.get("id"),
            "Student ID": row.get("student_id"),
            "Name": row.get("full_name"),
            "Email": row.get("email"),
            "Submitted at (UTC)": _naive_utc(row.get("created_at")),
        }
        for item_id, label in columns:
            value = responses.get(item_id)
            if with_labels and value is not None:
                try:
                    item = get_item(item_id)
                    text = next(
                        (lbl for lbl, val in item.options if val == value), str(value)
                    )
                    record[label] = f"{value} - {text}"
                except KeyError:
                    record[label] = value
            else:
                record[label] = value
        records.append(record)
    return pd.DataFrame.from_records(records)


def _codebook_frame() -> pd.DataFrame:
    records = []
    for inst in INSTRUMENTS.values():
        for item in inst.items:
            records.append(
                {
                    "Instrument": inst.short_name,
                    "Column": f"{inst.short_name} Q{item.number}",
                    "Item ID": item.id,
                    "Question": item.text,
                    "Response options": " | ".join(
                        f"{label}={value}" for label, value in item.options
                    ),
                }
            )
    return pd.DataFrame.from_records(records)


def _scoring_notes_frame() -> pd.DataFrame:
    notes = [
        (
            "ASRS-v1.1",
            "All 18 items are scored Never=0, Rarely=1, Sometimes=2, Often=3, Very "
            "Often=4. Part A (items 1-6) totals 0-24, Part B (items 7-18) totals "
            "0-48, and the whole scale totals 0-72. These point totals are a "
            "severity index: the source instrument publishes no cut-off for them. "
            "The screening decision uses Part A's shaded-box count instead: items "
            "1-3 count from 'Sometimes' upward and items 4-6 from 'Often' upward, "
            "and 4 or more shaded marks = symptoms highly consistent with ADHD in "
            "adults, further investigation warranted. In Part B, items 9, 12, 16 and "
            "18 shade from 'Sometimes' upward and the rest from 'Often' upward; "
            "those marks are cues only, with no diagnostic likelihood of their own.",
        ),
        (
            "PSS-10",
            "Reverse items 4, 5, 7, 8 (0=4, 1=3, 2=2, 3=1, 4=0), then sum all 10 "
            "items. Range 0-40. 0-13 low stress, 14-26 moderate stress, 27-40 high "
            "perceived stress.",
        ),
        (
            "WHO-5",
            "Sum the five items for a raw score of 0-25 (0 worst, 25 best), then "
            "multiply by 4 for a 0-100 percentage score.",
        ),
        (
            "rMEQ",
            "Sum the five item scores. Range 4-25. Lowest totals suggest an evening "
            "type, highest totals a morning type. Source notes evidence is "
            "insufficient to predict adaptation to night shifts.",
        ),
        (
            "HSPS",
            "Sum the 27 items, each rated 1 (Not at all) to 7 (Extremely). Range "
            "27-189. Higher totals indicate greater emotional and sensory reactivity. "
            "The source publishes no cut-off scores.",
        ),
    ]
    return pd.DataFrame(notes, columns=["Instrument", "Scoring rule (from source PDF)"])


def build_workbook(rows: list[dict[str, Any]]) -> bytes:
    """Build the combined multi-sheet workbook and return it as bytes."""
    instrument_keys = list(INSTRUMENTS.keys())

    base = _base_frame(rows)
    numeric_items = _responses_frame(rows, instrument_keys, with_labels=False)

    # The "combined" sheet: participant details, every score, and every raw item
    # answer side by side, one row per submission.
    if not base.empty:
        combined = base.merge(
            numeric_items.drop(
                columns=["Student ID", "Name", "Email", "Submitted at (UTC)"]
            ),
            on="Submission ID",
            how="left",
        )
    else:
        combined = base

    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        combined.to_excel(writer, sheet_name="Combined", index=False)
        base.to_excel(writer, sheet_name="Scores Summary", index=False)
        _responses_frame(rows, instrument_keys, with_labels=True).to_excel(
            writer, sheet_name="Responses (labelled)", index=False
        )
        for key in instrument_keys:
            inst = INSTRUMENTS[key]
            sheet = _responses_frame(rows, [key], with_labels=False)
            sheet.to_excel(writer, sheet_name=inst.short_name[:31], index=False)
        _codebook_frame().to_excel(writer, sheet_name="Codebook", index=False)
        _scoring_notes_frame().to_excel(writer, sheet_name="Scoring Rules", index=False)

        for worksheet in writer.book.worksheets:
            worksheet.freeze_panes = "A2"
            for column_cells in worksheet.columns:
                length = max(
                    (len(str(cell.value)) for cell in column_cells if cell.value),
                    default=10,
                )
                letter = column_cells[0].column_letter
                worksheet.column_dimensions[letter].width = min(max(length + 2, 12), 60)

    buffer.seek(0)
    return buffer.getvalue()
