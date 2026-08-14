"""ADHD screening battery - single-page Streamlit front end.

Sections are presented one at a time, OA style: participant details, then each
instrument in turn, then a review step, then feedback. Results are written to
the database and exported as a combined Excel workbook from the admin board.

Run with:  streamlit run app.py
"""

from __future__ import annotations

import time

import streamlit as st

from assessment import admin, db, keepalive
from assessment.instruments import ASRS, HSPS, INSTRUMENTS, PSS, RMEQ, WHO5, Instrument
from assessment.scoring import ScoreResult, score_all

st.set_page_config(
    page_title="ADHD Screening Battery",
    page_icon="🧠",
    layout="centered",
    initial_sidebar_state="collapsed",
)


# --------------------------------------------------------------------------
# Page plan - long instruments are split so no single screen is overwhelming
# --------------------------------------------------------------------------
@st.cache_resource
def _boot() -> dict:
    """One-time process setup: database tables and the keep-alive thread."""
    db.get_engine()
    return keepalive.start()


def _pages() -> list[dict]:
    pages: list[dict] = [{"kind": "intro", "title": "Welcome"}]
    pages.append({"kind": "details", "title": "About you"})

    def add(inst: Instrument, chunks: list[tuple[int, int]]) -> None:
        for index, (start, end) in enumerate(chunks, start=1):
            pages.append(
                {
                    "kind": "instrument",
                    "instrument": inst.key,
                    "start": start,
                    "end": end,
                    "part": index,
                    "parts": len(chunks),
                    "title": inst.short_name,
                }
            )

    add(ASRS, [(1, 6), (7, 18)])
    add(PSS, [(1, 10)])
    add(WHO5, [(1, 5)])
    add(RMEQ, [(1, 5)])
    add(HSPS, [(1, 9), (10, 18), (19, 27)])

    pages.append({"kind": "review", "title": "Review"})
    pages.append({"kind": "results", "title": "Your feedback"})
    return pages


PAGES = _pages()
TOTAL_STEPS = len(PAGES)


def _init_state() -> None:
    st.session_state.setdefault("page_index", 0)
    st.session_state.setdefault("responses", {})
    st.session_state.setdefault("participant", {})
    st.session_state.setdefault("started_at", time.time())
    st.session_state.setdefault("submission_id", None)
    st.session_state.setdefault("results", None)


def _goto(index: int) -> None:
    st.session_state.page_index = max(0, min(index, TOTAL_STEPS - 1))
    st.rerun()


# --------------------------------------------------------------------------
# Rendering helpers
# --------------------------------------------------------------------------
def _progress() -> None:
    index = st.session_state.page_index
    st.progress((index) / (TOTAL_STEPS - 1), text=f"Step {index + 1} of {TOTAL_STEPS}")


def _render_items(inst: Instrument, start: int, end: int) -> list[str]:
    """Render items ``start``..``end`` and return the ids still unanswered."""
    responses = st.session_state.responses
    unanswered: list[str] = []

    for item in inst.items:
        if not (start <= item.number <= end):
            continue

        current = responses.get(item.id)
        labels = item.labels
        index = None
        if current is not None:
            values = [value for _, value in item.options]
            if current in values:
                index = values.index(current)

        st.markdown(f"**{item.number}. {item.text}**")
        choice = st.radio(
            label=f"Response for item {item.number}",
            options=labels,
            index=index,
            key=f"widget_{item.id}",
            horizontal=len(labels) <= 7 and max(len(l) for l in labels) <= 24,
            label_visibility="collapsed",
        )
        if choice is None:
            unanswered.append(item.id)
        else:
            responses[item.id] = item.value_of(choice)
        st.write("")

    return unanswered


def _nav(on_next=None, next_label: str = "Next", allow_back: bool = True) -> None:
    left, right = st.columns([1, 1])
    if allow_back and st.session_state.page_index > 0:
        if left.button("Back", use_container_width=True):
            _goto(st.session_state.page_index - 1)
    if right.button(next_label, type="primary", use_container_width=True):
        if on_next is None or on_next():
            _goto(st.session_state.page_index + 1)


# --------------------------------------------------------------------------
# Pages
# --------------------------------------------------------------------------
def _page_intro() -> None:
    st.title("🧠 ADHD Screening Battery")
    st.write(
        "This assessment brings five validated questionnaires together in one "
        "sitting. You will move through them one section at a time, and you will "
        "get your scored feedback immediately at the end."
    )

    st.markdown(
        """
| Questionnaire | Items | What it looks at |
| --- | --- | --- |
| ASRS-v1.1 | 18 | Adult ADHD symptoms over the past 6 months |
| PSS-10 | 10 | Perceived stress over the last month |
| WHO-5 | 5 | Well-being over the last two weeks |
| rMEQ | 5 | Morning/evening chronotype |
| HSPS | 27 | Sensory processing sensitivity |
"""
    )
    st.caption("65 questions in total - most people finish in 10 to 15 minutes.")

    st.warning(
        "**This is a screening tool, not a diagnosis.** The results cannot "
        "diagnose ADHD or any other condition. If anything here concerns you, "
        "please discuss it with a qualified healthcare professional."
    )

    consent = st.checkbox(
        "I understand this is a screening tool and I consent to my responses "
        "being stored for review."
    )

    if st.button("Start assessment", type="primary", disabled=not consent):
        st.session_state.started_at = time.time()
        _goto(1)


def _page_details() -> None:
    st.header("About you")
    st.caption("Only your name is required. Everything else is optional.")

    participant = st.session_state.participant
    participant["full_name"] = st.text_input(
        "Full name", value=participant.get("full_name", "")
    )
    participant["email"] = st.text_input("Email", value=participant.get("email", ""))

    col1, col2 = st.columns(2)
    age_value = participant.get("age")
    participant["age"] = col1.number_input(
        "Age",
        min_value=0,
        max_value=120,
        value=age_value if isinstance(age_value, int) else None,
        placeholder="Optional",
    )
    gender_options = [
        "Prefer not to say",
        "Female",
        "Male",
        "Non-binary",
        "Other",
    ]
    participant["gender"] = col2.selectbox(
        "Gender",
        gender_options,
        index=gender_options.index(participant.get("gender", "Prefer not to say")),
    )
    participant["occupation"] = st.text_input(
        "Occupation", value=participant.get("occupation", "")
    )

    def validate() -> bool:
        if not (participant.get("full_name") or "").strip():
            st.error("Please enter your name.")
            return False
        return True

    _nav(on_next=validate)


def _page_instrument(page: dict) -> None:
    inst = INSTRUMENTS[page["instrument"]]

    st.header(inst.short_name)
    if page["parts"] > 1:
        st.caption(
            f"Part {page['part']} of {page['parts']} - questions "
            f"{page['start']} to {page['end']} of {len(inst.items)}"
        )
    st.info(inst.instructions)
    if inst.anchors:
        st.caption(" · ".join(inst.anchors))

    unanswered = _render_items(inst, page["start"], page["end"])

    def validate() -> bool:
        if unanswered:
            st.error(
                f"Please answer every question - {len(unanswered)} still "
                "unanswered on this page."
            )
            return False
        return True

    _nav(on_next=validate)


def _page_review() -> None:
    st.header("Review")
    responses = st.session_state.responses

    all_complete = True
    for page_index, page in enumerate(PAGES):
        if page["kind"] != "instrument":
            continue
        inst = INSTRUMENTS[page["instrument"]]
        item_ids = [
            item.id
            for item in inst.items
            if page["start"] <= item.number <= page["end"]
        ]
        missing = [i for i in item_ids if responses.get(i) is None]
        label = inst.short_name + (
            f" (part {page['part']})" if page["parts"] > 1 else ""
        )
        col1, col2 = st.columns([3, 1])
        if missing:
            all_complete = False
            col1.error(f"{label} - {len(missing)} unanswered")
        else:
            col1.success(f"{label} - complete")
        if col2.button("Edit", key=f"edit_{page_index}"):
            _goto(page_index)

    st.divider()
    st.session_state.participant["notes"] = st.text_area(
        "Anything you would like to add? (optional)",
        value=st.session_state.participant.get("notes", ""),
        placeholder="Context you would like whoever reviews this to know.",
    )

    if not all_complete:
        st.warning("Fill in the missing answers before submitting.")

    left, right = st.columns([1, 1])
    if left.button("Back", use_container_width=True):
        _goto(st.session_state.page_index - 1)
    if right.button(
        "Submit and see my results",
        type="primary",
        use_container_width=True,
        disabled=not all_complete,
    ):
        results = score_all(responses)
        duration = int(time.time() - st.session_state.started_at)
        try:
            submission_id = db.save_submission(
                st.session_state.participant, responses, results, duration
            )
            st.session_state.submission_id = submission_id
            st.session_state.pop("save_error", None)
        except Exception as exc:  # never lose the user's feedback over a DB error
            st.session_state.submission_id = None
            st.session_state.save_error = str(exc)
        st.session_state.results = results
        st.session_state.celebrated = False
        _goto(st.session_state.page_index + 1)


_TONE_STYLE = {
    "good": ("✅", "success"),
    "neutral": ("•", "info"),
    "warn": ("⚠️", "warning"),
    "flag": ("🚩", "error"),
}


def _render_result(result: ScoreResult) -> None:
    icon, style = _TONE_STYLE.get(result.band.tone, ("•", "info"))
    with st.container(border=True):
        top, bottom = st.columns([1, 3])
        suffix = "%" if result.headline_label == "percentage" else ""
        top.metric(result.name, f"{result.headline}{suffix}")
        bottom.markdown(f"### {icon} {result.band.label}")
        bottom.write(result.band.detail)
        if not result.band.from_source:
            bottom.caption(
                "Interpretation band is the conventional one from the wider "
                "literature; the source questionnaire does not print cut-offs."
            )
        with st.expander("Details and scoring notes"):
            if result.metrics:
                st.write(result.metrics)
            for note in result.notes:
                st.markdown(f"- {note}")


def _page_results() -> None:
    results: dict[str, ScoreResult] = st.session_state.results or {}
    if not st.session_state.get("celebrated"):
        st.balloons()
        st.session_state.celebrated = True
    st.title("Your feedback")

    if st.session_state.get("save_error"):
        st.error(
            "Your results were scored but could not be saved to the database: "
            f"{st.session_state['save_error']}"
        )
    elif st.session_state.submission_id:
        st.success("Your responses have been recorded. Thank you for taking part.")

    st.warning(
        "**These results are a screening aid, not a diagnosis.** Only a qualified "
        "healthcare professional can diagnose ADHD or any other condition."
    )

    for key in ("asrs", "pss", "who5", "rmeq", "hsps"):
        if key in results:
            _render_result(results[key])

    st.divider()
    if st.session_state.submission_id:
        st.caption(f"Reference: `{st.session_state.submission_id}`")

    if st.button("Start a new assessment"):
        for key in (
            "page_index",
            "responses",
            "participant",
            "results",
            "submission_id",
            "save_error",
            "celebrated",
        ):
            st.session_state.pop(key, None)
        for item_id in list(st.session_state.keys()):
            if str(item_id).startswith("widget_"):
                st.session_state.pop(item_id, None)
        st.rerun()


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------
def main() -> None:
    params = st.query_params

    # Health endpoint for the keep-alive pinger - render nothing heavy.
    if params.get("ping"):
        st.write("ok")
        return

    _boot()
    _init_state()

    if params.get("admin"):
        admin.render()
        return

    with st.sidebar:
        st.markdown("### ADHD Screening Battery")
        st.caption(
            "Five questionnaires, scored exactly as their source documents "
            "prescribe."
        )
        st.divider()
        st.link_button("Admin board", "?admin=1", use_container_width=True)

    _progress()
    page = PAGES[st.session_state.page_index]

    if page["kind"] == "intro":
        _page_intro()
    elif page["kind"] == "details":
        _page_details()
    elif page["kind"] == "instrument":
        _page_instrument(page)
    elif page["kind"] == "review":
        _page_review()
    elif page["kind"] == "results":
        _page_results()


if __name__ == "__main__":
    main()
