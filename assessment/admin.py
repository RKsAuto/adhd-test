"""Admin board, gated by an admin key."""

from __future__ import annotations

import hmac
import os
from datetime import datetime, timedelta, timezone

import pandas as pd
import streamlit as st

from . import db, keepalive
from .excel import build_workbook
from .instruments import INSTRUMENTS

SESSION_KEY = "admin_authenticated"


def _expected_key() -> str | None:
    key = os.environ.get("ADMIN_KEY", "")
    if not key:
        try:
            key = st.secrets.get("ADMIN_KEY", "")  # type: ignore[assignment]
        except Exception:
            key = ""
    return key or None


def _check_key(supplied: str) -> bool:
    expected = _expected_key()
    if not expected:
        return False
    return hmac.compare_digest(supplied.strip(), expected)


def _login_form() -> None:
    st.title("Admin board")
    st.caption("Restricted area. Enter the admin key to continue.")

    if _expected_key() is None:
        st.error(
            "No admin key is configured on this deployment. Set the `ADMIN_KEY` "
            "environment variable (or a `ADMIN_KEY` entry in Streamlit secrets) "
            "and restart the app."
        )
        return

    with st.form("admin_login"):
        supplied = st.text_input("Admin key", type="password")
        submitted = st.form_submit_button("Unlock", type="primary")

    if submitted:
        if _check_key(supplied):
            st.session_state[SESSION_KEY] = True
            st.rerun()
        else:
            st.error("Incorrect admin key.")


def _summary_metrics(rows: list[dict]) -> None:
    total = len(rows)
    positives = sum(1 for r in rows if r.get("asrs_screen_positive") == "Yes")
    high_stress = sum(1 for r in rows if (r.get("pss_total") or 0) >= 27)
    low_wellbeing = sum(
        1 for r in rows if r.get("who5_percentage") is not None
        and r["who5_percentage"] <= 50
    )

    def share(count: int) -> str | None:
        return f"{count / total:.0%} of all" if total else None

    cols = st.columns(4)
    cols[0].metric("Submissions", total)
    cols[1].metric(
        "ASRS screen positive", positives, share(positives), delta_color="off"
    )
    cols[2].metric(
        "High perceived stress", high_stress, share(high_stress), delta_color="off"
    )
    cols[3].metric(
        "WHO-5 at or below 50%", low_wellbeing, share(low_wellbeing), delta_color="off"
    )


def _submissions_table(rows: list[dict]) -> pd.DataFrame:
    frame = pd.DataFrame(
        [
            {
                "Submitted (UTC)": r.get("created_at"),
                "Student ID": r.get("student_id"),
                "Name": r.get("full_name"),
                "Email": r.get("email"),
                "Age": r.get("age"),
                "ASRS Part A (/6)": r.get("asrs_part_a_count"),
                "ASRS positive": r.get("asrs_screen_positive"),
                "PSS-10": r.get("pss_total"),
                "WHO-5 %": r.get("who5_percentage"),
                "rMEQ": r.get("rmeq_total"),
                "HSPS": r.get("hsps_total"),
                "ID": r.get("id"),
            }
            for r in rows
        ]
    )
    return frame


def _detail_view(rows: list[dict]) -> None:
    if not rows:
        return
    st.subheader("Inspect a submission")
    labels = {
        f"{r.get('created_at')} - {r.get('student_id') or '?'} - "
        f"{r.get('full_name') or 'Anonymous'} ({r['id'][:8]})": r["id"]
        for r in rows
    }
    chosen = st.selectbox("Submission", list(labels.keys()), index=0)
    submission = db.fetch_one(labels[chosen])
    if not submission:
        st.warning("That submission no longer exists.")
        return

    left, right = st.columns([1, 1])
    with left:
        st.markdown("**Participant**")
        st.write(
            {
                "Name": submission.get("full_name"),
                "Student ID": submission.get("student_id"),
                "Email": submission.get("email"),
                "Age": submission.get("age"),
                "Gender": submission.get("gender"),
                "Occupation": submission.get("occupation"),
                "Duration (s)": submission.get("duration_seconds"),
            }
        )
        if submission.get("notes"):
            st.markdown("**Participant notes**")
            st.info(submission["notes"])
    with right:
        st.markdown("**Scores**")
        st.write(submission.get("scores") or {})

    responses = submission.get("responses") or {}
    for inst in INSTRUMENTS.values():
        with st.expander(f"{inst.short_name} responses"):
            records = []
            for item in inst.items:
                value = responses.get(item.id)
                label = next(
                    (lbl for lbl, val in item.options if val == value), ""
                ) if value is not None else ""
                records.append(
                    {
                        "#": item.number,
                        "Question": item.text,
                        "Answer": label,
                        "Score": value,
                    }
                )
            st.dataframe(
                pd.DataFrame(records), hide_index=True, use_container_width=True
            )

    with st.expander("Delete this submission"):
        st.warning(
            "Deleting is permanent. Download the Excel export first if you need "
            "a copy."
        )
        confirm = st.text_input(
            "Type DELETE to confirm", key=f"confirm_{submission['id']}"
        )
        if st.button("Delete permanently", type="secondary"):
            if confirm.strip() == "DELETE":
                db.delete_submission(submission["id"])
                st.success("Submission deleted.")
                st.rerun()
            else:
                st.error("Type DELETE in the box to confirm.")


def render() -> None:
    """Render the admin board, prompting for the admin key when needed."""
    if not st.session_state.get(SESSION_KEY):
        _login_form()
        return

    header, logout = st.columns([4, 1])
    header.title("Admin board")
    if logout.button("Log out"):
        st.session_state[SESSION_KEY] = False
        st.rerun()

    rows = db.fetch_all()

    st.caption(f"Storage backend: {db.backend_name()}")
    _summary_metrics(rows)
    st.divider()

    if not rows:
        st.info("No submissions yet.")
        _keepalive_panel()
        return

    # Filters
    with st.expander("Filters", expanded=False):
        col1, col2, col3 = st.columns(3)
        days = col1.selectbox(
            "Date range", ["All time", "Last 7 days", "Last 30 days", "Last 90 days"]
        )
        only_positive = col2.checkbox("ASRS screen positive only")
        search = col3.text_input("Search name, student ID or email")

    filtered = rows
    if days != "All time":
        window = {"Last 7 days": 7, "Last 30 days": 30, "Last 90 days": 90}[days]
        cutoff = datetime.now(timezone.utc) - timedelta(days=window)
        filtered = [
            r
            for r in filtered
            if r.get("created_at")
            and _as_utc(r["created_at"]) >= cutoff
        ]
    if only_positive:
        filtered = [r for r in filtered if r.get("asrs_screen_positive") == "Yes"]
    if search:
        needle = search.strip().lower()
        filtered = [
            r
            for r in filtered
            if needle in (r.get("full_name") or "").lower()
            or needle in (r.get("student_id") or "").lower()
            or needle in (r.get("email") or "").lower()
        ]

    st.subheader(f"Submissions ({len(filtered)})")
    st.dataframe(
        _submissions_table(filtered), hide_index=True, use_container_width=True
    )

    workbook = build_workbook(filtered)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M")
    st.download_button(
        "Download combined Excel",
        data=workbook,
        file_name=f"adhd-assessment-export-{stamp}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        type="primary",
    )
    st.caption(
        "The workbook contains a Combined sheet (participant details + all scores + "
        "every item answer), a scores summary, labelled responses, one sheet per "
        "instrument, a codebook and the scoring rules."
    )

    st.divider()
    _detail_view(filtered)
    st.divider()
    _keepalive_panel()


def _as_utc(value) -> datetime:
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _keepalive_panel() -> None:
    state = keepalive.status()
    with st.expander("Keep-alive status"):
        if not state.get("enabled"):
            st.info(
                "Self-ping is off. Set `SELF_PING_URL` to this app's public URL "
                "(and optionally `SELF_PING_INTERVAL`, default 600s) to keep the "
                "container awake."
            )
            return
        st.write(
            {
                "URL": state.get("url"),
                "Interval (s)": state.get("interval"),
                "Pings sent": state.get("ping_count"),
                "Errors": state.get("error_count"),
                "Last status": state.get("last_status"),
                "Last ping": (
                    datetime.fromtimestamp(
                        float(state["last_ping"]), tz=timezone.utc
                    ).strftime("%Y-%m-%d %H:%M:%S UTC")
                    if state.get("last_ping")
                    else "not yet"
                ),
            }
        )
