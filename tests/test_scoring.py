"""Tests for the scoring rules, checked against the source PDFs."""

from __future__ import annotations

import pytest

from assessment.instruments import (
    ASRS,
    ASRS_SHADED_THRESHOLD,
    HSPS,
    INSTRUMENTS,
    PSS,
    PSS_REVERSED,
    RMEQ,
    WHO5,
)
from assessment.scoring import (
    score_asrs,
    score_all,
    score_hsps,
    score_pss,
    score_rmeq,
    score_who5,
)


def fill(instrument, value: int) -> dict[str, int]:
    return {item.id: value for item in instrument.items}


# ---------------------------------------------------------------- instruments
def test_item_counts():
    assert len(ASRS.items) == 18
    assert len(PSS.items) == 10
    assert len(WHO5.items) == 5
    assert len(RMEQ.items) == 5
    assert len(HSPS.items) == 27


def test_every_item_has_unique_id():
    ids = [item.id for inst in INSTRUMENTS.values() for item in inst.items]
    assert len(ids) == len(set(ids)) == 65


# ---------------------------------------------------------------------- ASRS
def test_asrs_shading_matches_source_form():
    """Items 1-3 shade from Sometimes(2); 4-6 from Often(3).

    In Part B only items 9, 12, 16 and 18 shade from Sometimes.
    """
    assert [ASRS_SHADED_THRESHOLD[f"asrs_{n}"] for n in range(1, 7)] == [2, 2, 2, 3, 3, 3]
    sometimes_in_part_b = [
        n for n in range(7, 19) if ASRS_SHADED_THRESHOLD[f"asrs_{n}"] == 2
    ]
    assert sometimes_in_part_b == [9, 12, 16, 18]


def test_asrs_all_never_is_negative_screen():
    result = score_asrs(fill(ASRS, 0))
    assert result.headline == 0
    assert result.metrics["part_a_screen_positive"] == "No"


def test_asrs_all_very_often_is_positive_screen():
    result = score_asrs(fill(ASRS, 4))
    assert result.headline == 6
    assert result.metrics["part_a_screen_positive"] == "Yes"
    assert result.metrics["part_b_shaded_count"] == 12
    assert result.metrics["total_raw_sum"] == 18 * 4


def test_asrs_sometimes_everywhere_counts_only_items_1_to_3():
    """'Sometimes' is inside the shading for items 1-3 but not 4-6."""
    result = score_asrs(fill(ASRS, 2))
    assert result.headline == 3
    assert result.metrics["part_a_screen_positive"] == "No"
    # Part B: only items 9, 12, 16, 18 shade from Sometimes
    assert result.metrics["part_b_shaded_count"] == 4


def test_asrs_threshold_is_four_marks():
    responses = fill(ASRS, 0)
    # three shaded marks -> negative
    responses.update({"asrs_1": 2, "asrs_2": 2, "asrs_3": 2})
    assert score_asrs(responses).metrics["part_a_screen_positive"] == "No"
    # a fourth, using an item that needs 'Often' -> positive
    responses["asrs_4"] = 3
    result = score_asrs(responses)
    assert result.headline == 4
    assert result.metrics["part_a_screen_positive"] == "Yes"


def test_asrs_often_on_item_4_counts_but_sometimes_does_not():
    responses = fill(ASRS, 0)
    responses["asrs_4"] = 2
    assert score_asrs(responses).headline == 0
    responses["asrs_4"] = 3
    assert score_asrs(responses).headline == 1


def test_asrs_incomplete_raises():
    responses = fill(ASRS, 1)
    del responses["asrs_7"]
    with pytest.raises(ValueError, match="asrs_7"):
        score_asrs(responses)


# ----------------------------------------------------------------------- PSS
def test_pss_all_never_scores_reversed_items():
    """0 on every item: items 4,5,7,8 reverse to 4 each, so the total is 16."""
    result = score_pss(fill(PSS, 0))
    assert result.headline == 16
    assert result.band.label == "Moderate perceived stress"


def test_pss_all_very_often():
    """4 on every item: the four reversed items become 0, so 6*4 = 24."""
    assert score_pss(fill(PSS, 4)).headline == 24


def test_pss_maximum_possible_is_40():
    responses = fill(PSS, 4)
    for item_id in ("pss_4", "pss_5", "pss_7", "pss_8"):
        responses[item_id] = 0  # reverses to 4
    result = score_pss(responses)
    assert result.headline == 40
    assert result.band.label == "High perceived stress"


def test_pss_minimum_possible_is_zero():
    responses = fill(PSS, 0)
    for item_id in ("pss_4", "pss_5", "pss_7", "pss_8"):
        responses[item_id] = 4  # reverses to 0
    result = score_pss(responses)
    assert result.headline == 0
    assert result.band.label == "Low perceived stress"


@pytest.mark.parametrize(
    "total,expected",
    [(13, "Low perceived stress"), (14, "Moderate perceived stress"),
     (26, "Moderate perceived stress"), (27, "High perceived stress")],
)
def test_pss_band_boundaries(total, expected):
    # Build a response set summing to exactly `total`. Each item can contribute
    # 0-4 to the total; for a reversed item the raw answer is 4 - contribution.
    responses: dict[str, int] = {}
    remaining = total
    for item in PSS.items:
        contribution = min(4, remaining)
        remaining -= contribution
        responses[item.id] = (
            4 - contribution if item.id in PSS_REVERSED else contribution
        )
    assert remaining == 0
    result = score_pss(responses)
    assert result.headline == total
    assert result.band.label == expected


# ---------------------------------------------------------------------- WHO-5
def test_who5_raw_and_percentage():
    result = score_who5(fill(WHO5, 5))
    assert result.metrics["raw_score"] == 25
    assert result.headline == 100

    result = score_who5(fill(WHO5, 0))
    assert result.metrics["raw_score"] == 0
    assert result.headline == 0


def test_who5_percentage_is_raw_times_four():
    responses = {"who5_1": 3, "who5_2": 2, "who5_3": 4, "who5_4": 1, "who5_5": 0}
    result = score_who5(responses)
    assert result.metrics["raw_score"] == 10
    assert result.headline == 40


def test_who5_low_wellbeing_band_is_flagged_as_not_from_source():
    result = score_who5(fill(WHO5, 2))  # raw 10 -> 40%
    assert result.band.label == "Low well-being"
    assert result.band.from_source is False


# ----------------------------------------------------------------------- rMEQ
def test_rmeq_range_is_4_to_25():
    lowest = {"rmeq_1": 1, "rmeq_2": 1, "rmeq_3": 1, "rmeq_4": 1, "rmeq_5": 0}
    assert score_rmeq(lowest).headline == 4
    assert score_rmeq(lowest).band.label == "Evening type"

    highest = {"rmeq_1": 5, "rmeq_2": 4, "rmeq_3": 5, "rmeq_4": 5, "rmeq_5": 6}
    assert score_rmeq(highest).headline == 25
    assert score_rmeq(highest).band.label == "Morning type"


def test_rmeq_option_scores_match_the_pdf():
    assert RMEQ.item("rmeq_1").value_of("5 a.m. - 6:30 a.m.") == 5
    assert RMEQ.item("rmeq_1").value_of("11 a.m. - 12 noon") == 1
    assert RMEQ.item("rmeq_2").value_of("Very tired") == 1
    assert RMEQ.item("rmeq_2").value_of("Very refreshed") == 4
    assert RMEQ.item("rmeq_3").value_of("8 p.m. - 9 p.m.") == 5
    assert RMEQ.item("rmeq_4").value_of("10 p.m. - 5 a.m.") == 1
    assert RMEQ.item("rmeq_4").value_of("5 a.m. - 8 a.m.") == 5
    assert RMEQ.item("rmeq_5").value_of("Definitely a “morning” type") == 6
    assert RMEQ.item("rmeq_5").value_of("Definitely an “evening” type") == 0


def test_rmeq_intermediate_band():
    responses = {"rmeq_1": 3, "rmeq_2": 3, "rmeq_3": 3, "rmeq_4": 3, "rmeq_5": 2}
    result = score_rmeq(responses)
    assert result.headline == 14
    assert result.band.label == "Intermediate type"


# ----------------------------------------------------------------------- HSPS
def test_hsps_range_is_27_to_189():
    assert score_hsps(fill(HSPS, 1)).headline == 27
    assert score_hsps(fill(HSPS, 7)).headline == 189


def test_hsps_mean_item_score():
    result = score_hsps(fill(HSPS, 4))
    assert result.headline == 108
    assert result.metrics["mean_item_score"] == 4.0


def test_hsps_options_are_one_to_seven():
    assert [value for _, value in HSPS.items[0].options] == [1, 2, 3, 4, 5, 6, 7]


# ------------------------------------------------------------------ score_all
def test_score_all_skips_incomplete_instruments():
    responses: dict[str, int] = {}
    responses.update(fill(ASRS, 1))
    responses.update(fill(PSS, 1))
    results = score_all(responses)
    assert set(results) == {"asrs", "pss"}


def test_score_all_complete_battery():
    responses: dict[str, int] = {}
    for inst in INSTRUMENTS.values():
        for item in inst.items:
            responses[item.id] = item.options[0][1]
    results = score_all(responses)
    assert set(results) == {"asrs", "pss", "who5", "rmeq", "hsps"}
    for result in results.values():
        assert result.band.label
        assert result.as_row()
