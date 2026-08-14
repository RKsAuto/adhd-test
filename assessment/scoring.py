"""Scoring and feedback generation.

Each ``score_*`` function implements the scoring instructions printed in the
corresponding source PDF. Where a widely used interpretation band exists in the
literature but is NOT printed in the source PDF, it is included but marked with
``from_source=False`` so the UI can label it honestly.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .instruments import (
    ASRS,
    ASRS_PART_A,
    ASRS_PART_B,
    ASRS_SHADED_THRESHOLD,
    HSPS,
    INSTRUMENTS,
    PSS,
    PSS_MAX_ITEM_VALUE,
    PSS_REVERSED,
    RMEQ,
    WHO5,
)

Responses = dict[str, int]


@dataclass
class Band:
    """An interpretation band for a score."""

    label: str
    detail: str
    tone: str = "neutral"  # "good" | "neutral" | "warn" | "flag"
    from_source: bool = True


@dataclass
class ScoreResult:
    key: str
    name: str
    headline: str            # the single number a user cares about
    headline_label: str
    band: Band
    metrics: dict[str, float | int | str] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def as_row(self) -> dict[str, float | int | str]:
        """Flat representation for the combined Excel export."""
        row = {
            f"{self.key}_{self.headline_label}": self.headline,
            f"{self.key}_interpretation": self.band.label,
        }
        for name, value in self.metrics.items():
            row[f"{self.key}_{name}"] = value
        return row


def _require(responses: Responses, item_ids: list[str]) -> list[int]:
    missing = [i for i in item_ids if responses.get(i) is None]
    if missing:
        raise ValueError(f"missing responses for: {', '.join(missing)}")
    return [int(responses[i]) for i in item_ids]


# --------------------------------------------------------------------------
# ASRS v1.1
# --------------------------------------------------------------------------
def score_asrs(responses: Responses) -> ScoreResult:
    """Score the ASRS-v1.1 Symptom Checklist.

    Per the source PDF: "Score Part A. If four or more marks appear in the
    darkly shaded boxes within Part A then the patient has symptoms highly
    consistent with ADHD in adults and further investigation is warranted."

    Part B carries no total score and no diagnostic likelihood; its shaded
    marks are reported only as additional cues.
    """
    _require(responses, ASRS.item_ids)

    part_a_hits = [
        item_id
        for item_id in ASRS_PART_A
        if responses[item_id] >= ASRS_SHADED_THRESHOLD[item_id]
    ]
    part_b_hits = [
        item_id
        for item_id in ASRS_PART_B
        if responses[item_id] >= ASRS_SHADED_THRESHOLD[item_id]
    ]

    part_a_count = len(part_a_hits)
    positive = part_a_count >= 4

    if positive:
        band = Band(
            label="Symptoms highly consistent with ADHD in adults",
            detail=(
                f"{part_a_count} of the 6 Part A responses fell in the darkly "
                "shaded boxes, at or above the screener's threshold of 4, so "
                "further investigation is warranted. This is a screening result, "
                "not a diagnosis."
            ),
            tone="flag",
        )
    else:
        band = Band(
            label="Below the screening threshold",
            detail=(
                f"{part_a_count} of the 6 Part A responses fell in the darkly shaded "
                "boxes, below the threshold of 4 used by the ASRS-v1.1 screener. "
                "This does not rule out ADHD - if the symptoms affect your daily "
                "life, discuss them with a healthcare professional."
            ),
            tone="good",
        )

    return ScoreResult(
        key="asrs",
        name=ASRS.short_name,
        headline=part_a_count,
        headline_label="part_a_shaded_count",
        band=band,
        metrics={
            "part_a_screen_positive": "Yes" if positive else "No",
            "part_b_shaded_count": len(part_b_hits),
            "part_a_raw_sum": sum(responses[i] for i in ASRS_PART_A),
            "part_b_raw_sum": sum(responses[i] for i in ASRS_PART_B),
            "total_raw_sum": sum(responses[i] for i in ASRS.item_ids),
        },
        notes=[
            "Part A (6 items) is the ASRS-v1.1 Screener and is the only part with a "
            "scoring threshold.",
            "Part B frequencies are additional cues only - the source instrument "
            "assigns no total score or diagnostic likelihood to those 12 items.",
            "Raw sums are recorded for research use; they are not part of the "
            "published scoring rule.",
        ],
    )


# --------------------------------------------------------------------------
# PSS-10
# --------------------------------------------------------------------------
def score_pss(responses: Responses) -> ScoreResult:
    """Score the Perceived Stress Scale.

    Per the source PDF: reverse items 4, 5, 7 and 8 (0=4, 1=3, 2=2, 3=1, 4=0),
    then sum. Range 0-40. 0-13 low, 14-26 moderate, 27-40 high.
    """
    _require(responses, PSS.item_ids)

    total = 0
    for item_id in PSS.item_ids:
        value = int(responses[item_id])
        if item_id in PSS_REVERSED:
            value = PSS_MAX_ITEM_VALUE - value
        total += value

    if total <= 13:
        band = Band(
            "Low perceived stress",
            "Scores from 0-13 are considered low stress.",
            tone="good",
        )
    elif total <= 26:
        band = Band(
            "Moderate perceived stress",
            "Scores from 14-26 are considered moderate stress.",
            tone="warn",
        )
    else:
        band = Band(
            "High perceived stress",
            "Scores from 27-40 are considered high perceived stress.",
            tone="flag",
        )

    return ScoreResult(
        key="pss",
        name=PSS.short_name,
        headline=total,
        headline_label="total",
        band=band,
        metrics={"max_possible": 40},
        notes=[
            "Items 4, 5, 7 and 8 are reverse-scored before summing.",
            "Higher scores indicate higher perceived stress.",
        ],
    )


# --------------------------------------------------------------------------
# WHO-5
# --------------------------------------------------------------------------
def score_who5(responses: Responses) -> ScoreResult:
    """Score the WHO-5 Well-being Index.

    Per the source PDF: sum the five answers for a raw score of 0-25, then
    multiply by 4 for a percentage score of 0-100.
    """
    _require(responses, WHO5.item_ids)

    raw = sum(int(responses[i]) for i in WHO5.item_ids)
    percentage = raw * 4

    # The source PDF states only that 0 is the worst and 25/100 the best
    # possible quality of life. The <=50% screening cut-off below is the
    # conventional one from the WHO-5 literature, not from this PDF.
    if percentage <= 50:
        band = Band(
            "Low well-being",
            (
                "A percentage score of 50 or below is commonly used as a prompt to "
                "look further at low mood and well-being."
            ),
            tone="flag",
            from_source=False,
        )
    elif percentage <= 75:
        band = Band(
            "Moderate well-being",
            "Well-being sits in the middle of the scale.",
            tone="warn",
            from_source=False,
        )
    else:
        band = Band(
            "Good well-being",
            "Well-being sits in the upper part of the scale.",
            tone="good",
            from_source=False,
        )

    return ScoreResult(
        key="who5",
        name=WHO5.short_name,
        headline=percentage,
        headline_label="percentage",
        band=band,
        metrics={"raw_score": raw, "max_raw": 25},
        notes=[
            "Raw score ranges 0-25, where 0 is the worst and 25 the best possible "
            "quality of life. The percentage score is the raw score multiplied by 4.",
            "The banding above is the conventional WHO-5 interpretation; the source "
            "PDF itself prescribes only the raw and percentage scores.",
        ],
    )


# --------------------------------------------------------------------------
# rMEQ
# --------------------------------------------------------------------------
def score_rmeq(responses: Responses) -> ScoreResult:
    """Score the reduced Morningness/Eveningness Questionnaire.

    Per the source PDF: sum the item scores, giving a range of 4-25. "The
    smallest total scores suggest an evening type and the highest scores
    suggest a morning type."
    """
    _require(responses, RMEQ.item_ids)

    total = sum(int(responses[i]) for i in RMEQ.item_ids)

    # The source PDF gives the direction but no numeric cut-offs. The 11/18
    # boundaries below are the conventional rMEQ ones.
    if total <= 11:
        band = Band(
            "Evening type",
            "Lower total scores suggest an evening type.",
            tone="neutral",
            from_source=False,
        )
    elif total <= 17:
        band = Band(
            "Intermediate type",
            "Mid-range scores suggest neither a strong morning nor evening preference.",
            tone="neutral",
            from_source=False,
        )
    else:
        band = Band(
            "Morning type",
            "Higher total scores suggest a morning type.",
            tone="neutral",
            from_source=False,
        )

    return ScoreResult(
        key="rmeq",
        name=RMEQ.short_name,
        headline=total,
        headline_label="total",
        band=band,
        metrics={"min_possible": 4, "max_possible": 25},
        notes=[
            "Totals range from 4 to 25. The smallest totals suggest an evening type "
            "and the highest totals suggest a morning type.",
            "The source PDF notes that research evidence is insufficient to support "
            "using this score to predict a person's ability to adapt to night shifts.",
            "The numeric type boundaries used here are the conventional ones; the "
            "source PDF gives the direction of the scale only.",
        ],
    )


# --------------------------------------------------------------------------
# HSPS
# --------------------------------------------------------------------------
def score_hsps(responses: Responses) -> ScoreResult:
    """Score the Highly Sensitive Person Scale.

    Per the source PDF: sum the 27 items, giving a range of 27-189. "A higher
    total score on the HSPS indicates a higher level of sensitivity."
    """
    _require(responses, HSPS.item_ids)

    total = sum(int(responses[i]) for i in HSPS.item_ids)
    mean_item = round(total / len(HSPS.items), 2)

    # The source PDF supplies no cut-offs at all, so these thirds of the
    # 27-189 range are descriptive only.
    if total <= 80:
        band = Band(
            "Lower end of the sensitivity range",
            "Your total sits in the lower third of the 27-189 range.",
            tone="neutral",
            from_source=False,
        )
    elif total <= 134:
        band = Band(
            "Middle of the sensitivity range",
            "Your total sits in the middle third of the 27-189 range.",
            tone="neutral",
            from_source=False,
        )
    else:
        band = Band(
            "Higher end of the sensitivity range",
            "Your total sits in the upper third of the 27-189 range, suggesting "
            "greater emotional and sensory reactivity.",
            tone="neutral",
            from_source=False,
        )

    return ScoreResult(
        key="hsps",
        name=HSPS.short_name,
        headline=total,
        headline_label="total",
        band=band,
        metrics={"mean_item_score": mean_item, "min_possible": 27, "max_possible": 189},
        notes=[
            "Scores range from 27 to 189. A higher total indicates a higher level of "
            "sensitivity across different situations and stimuli.",
            "The source PDF publishes no cut-off scores, so the descriptive band "
            "above simply splits the possible range into thirds.",
        ],
    )


SCORERS = {
    "asrs": score_asrs,
    "pss": score_pss,
    "who5": score_who5,
    "rmeq": score_rmeq,
    "hsps": score_hsps,
}


def score_all(responses: Responses) -> dict[str, ScoreResult]:
    """Score every instrument that has a complete set of responses."""
    results: dict[str, ScoreResult] = {}
    for key, scorer in SCORERS.items():
        item_ids = INSTRUMENTS[key].item_ids
        if all(responses.get(i) is not None for i in item_ids):
            results[key] = scorer(responses)
    return results


def flatten_scores(results: dict[str, ScoreResult]) -> dict[str, float | int | str]:
    """Merge every ScoreResult into one flat dict for storage/export."""
    row: dict[str, float | int | str] = {}
    for result in results.values():
        row.update(result.as_row())
    return row
