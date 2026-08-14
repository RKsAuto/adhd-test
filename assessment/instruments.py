"""Instrument definitions.

Every item text, response label and response value in this module is
transcribed directly from the source PDFs. Nothing here is invented: if a
value is not stated by the source PDF it does not appear here, and any
interpretation band that comes from the wider literature rather than the PDF
is flagged as such in ``scoring.py``.

Sources
-------
ASRS  : Adult ADHD Self-Report Scale (ASRS-v1.1) Symptom Checklist (WHO)
PSS   : Perceived Stress Scale (Cohen, 1983) - NH EAP reprint
WHO5  : WHO-5 Well-being Index
RMEQ  : Morningness/Eveningness Questionnaire (Adan & Almirall, 1991), reduced form
HSPS  : Highly Sensitive Person Scale (Aron & Aron, 1997)
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Item:
    """A single questionnaire item."""

    id: str
    number: int
    text: str
    options: tuple[tuple[str, int], ...]

    @property
    def labels(self) -> list[str]:
        return [label for label, _ in self.options]

    def value_of(self, label: str) -> int:
        for opt_label, value in self.options:
            if opt_label == label:
                return value
        raise KeyError(f"{label!r} is not a valid response for item {self.id}")


@dataclass(frozen=True)
class Instrument:
    key: str
    name: str
    short_name: str
    instructions: str
    items: tuple[Item, ...]
    source: str
    shared_scale: bool = True  # every item uses the same response options
    anchors: tuple[str, ...] = field(default=())

    def item(self, item_id: str) -> Item:
        for it in self.items:
            if it.id == item_id:
                return it
        raise KeyError(item_id)

    @property
    def item_ids(self) -> list[str]:
        return [it.id for it in self.items]


# --------------------------------------------------------------------------
# ASRS v1.1
# --------------------------------------------------------------------------
# "place an X in the box that best describes how you have felt and conducted
#  yourself over the past 6 months"
ASRS_OPTIONS: tuple[tuple[str, int], ...] = (
    ("Never", 0),
    ("Rarely", 1),
    ("Sometimes", 2),
    ("Often", 3),
    ("Very Often", 4),
)

_ASRS_TEXTS = [
    # Part A - items 1-6
    "How often do you have trouble wrapping up the final details of a project, "
    "once the challenging parts have been done?",
    "How often do you have difficulty getting things in order when you have to do "
    "a task that requires organization?",
    "How often do you have problems remembering appointments or obligations?",
    "When you have a task that requires a lot of thought, how often do you avoid "
    "or delay getting started?",
    "How often do you fidget or squirm with your hands or feet when you have "
    "to sit down for a long time?",
    "How often do you feel overly active and compelled to do things, like you "
    "were driven by a motor?",
    # Part B - items 7-18
    "How often do you make careless mistakes when you have to work on a boring or "
    "difficult project?",
    "How often do you have difficulty keeping your attention when you are doing "
    "boring or repetitive work?",
    "How often do you have difficulty concentrating on what people say to you, "
    "even when they are speaking to you directly?",
    "How often do you misplace or have difficulty finding things at home or at work?",
    "How often are you distracted by activity or noise around you?",
    "How often do you leave your seat in meetings or other situations in which "
    "you are expected to remain seated?",
    "How often do you feel restless or fidgety?",
    "How often do you have difficulty unwinding and relaxing when you have time "
    "to yourself?",
    "How often do you find yourself talking too much when you are in social situations?",
    "When you're in a conversation, how often do you find yourself finishing "
    "the sentences of the people you are talking to, before they can finish "
    "them themselves?",
    "How often do you have difficulty waiting your turn in situations when "
    "turn taking is required?",
    "How often do you interrupt others when they are busy?",
]

ASRS = Instrument(
    key="asrs",
    name="Adult ADHD Self-Report Scale (ASRS-v1.1) Symptom Checklist",
    short_name="ASRS-v1.1",
    instructions=(
        "Rate yourself on each of the criteria below. As you answer each question, "
        "choose the response that best describes how you have felt and conducted "
        "yourself **over the past 6 months**."
    ),
    items=tuple(
        Item(id=f"asrs_{n}", number=n, text=text, options=ASRS_OPTIONS)
        for n, text in enumerate(_ASRS_TEXTS, start=1)
    ),
    source="World Health Organization / Workgroup on Adult ADHD (Adler, Kessler, Spencer)",
)

# The "darkly shaded boxes" of the printed form, read directly off the shading
# of page 2 of the source PDF. The value is the lowest response VALUE that
# falls inside the shaded region for that item.
#   Part A items 1-3 shade Sometimes/Often/Very Often  -> threshold 2
#   Part A items 4-6 shade Often/Very Often            -> threshold 3
#   Part B items 9, 12, 16, 18 shade Sometimes upward  -> threshold 2
#   all other Part B items shade Often/Very Often      -> threshold 3
ASRS_SHADED_THRESHOLD: dict[str, int] = {
    "asrs_1": 2,
    "asrs_2": 2,
    "asrs_3": 2,
    "asrs_4": 3,
    "asrs_5": 3,
    "asrs_6": 3,
    "asrs_7": 3,
    "asrs_8": 3,
    "asrs_9": 2,
    "asrs_10": 3,
    "asrs_11": 3,
    "asrs_12": 2,
    "asrs_13": 3,
    "asrs_14": 3,
    "asrs_15": 3,
    "asrs_16": 2,
    "asrs_17": 3,
    "asrs_18": 2,
}

ASRS_PART_A = [f"asrs_{n}" for n in range(1, 7)]
ASRS_PART_B = [f"asrs_{n}" for n in range(7, 19)]


# --------------------------------------------------------------------------
# Perceived Stress Scale (PSS-10)
# --------------------------------------------------------------------------
PSS_OPTIONS: tuple[tuple[str, int], ...] = (
    ("Never", 0),
    ("Almost never", 1),
    ("Sometimes", 2),
    ("Fairly often", 3),
    ("Very often", 4),
)

_PSS_TEXTS = [
    "In the last month, how often have you been upset because of something that "
    "happened unexpectedly?",
    "In the last month, how often have you felt that you were unable to control "
    "the important things in your life?",
    "In the last month, how often have you felt nervous and stressed?",
    "In the last month, how often have you felt confident about your ability to "
    "handle your personal problems?",
    "In the last month, how often have you felt that things were going your way?",
    "In the last month, how often have you found that you could not cope with "
    "all the things that you had to do?",
    "In the last month, how often have you been able to control irritations in "
    "your life?",
    "In the last month, how often have you felt that you were on top of things?",
    "In the last month, how often have you been angered because of things that "
    "happened that were outside of your control?",
    "In the last month, how often have you felt difficulties were piling up so "
    "high that you could not overcome them?",
]

PSS = Instrument(
    key="pss",
    name="Perceived Stress Scale (PSS-10)",
    short_name="PSS-10",
    instructions=(
        "The questions below ask about your feelings and thoughts **during the last "
        "month**. In each case, indicate how often you felt or thought a certain way. "
        "Some questions are similar, but treat each one as a separate question. "
        "The best approach is to answer fairly quickly - don't count up the number of "
        "times you felt a particular way, just give a reasonable estimate."
    ),
    items=tuple(
        Item(id=f"pss_{n}", number=n, text=text, options=PSS_OPTIONS)
        for n, text in enumerate(_PSS_TEXTS, start=1)
    ),
    source="Perceived Stress Scale - State of New Hampshire Employee Assistance Program",
)

# "First, reverse your scores for questions 4, 5, 7, and 8."
PSS_REVERSED = ["pss_4", "pss_5", "pss_7", "pss_8"]
PSS_MAX_ITEM_VALUE = 4


# --------------------------------------------------------------------------
# WHO-5 Well-being Index
# --------------------------------------------------------------------------
WHO5_OPTIONS: tuple[tuple[str, int], ...] = (
    ("All of the time", 5),
    ("Most of the time", 4),
    ("More than half the time", 3),
    ("Less than half the time", 2),
    ("Some of the time", 1),
    ("At no time", 0),
)

_WHO5_TEXTS = [
    "I have felt cheerful and in good spirits.",
    "I have felt calm and relaxed.",
    "I have felt active and vigorous.",
    "I woke up feeling fresh and rested.",
    "My daily life has been filled with things that interest me.",
]

WHO5 = Instrument(
    key="who5",
    name="WHO-5 Well-being Index",
    short_name="WHO-5",
    instructions=(
        "Please respond to each item regarding how you felt **in the last two weeks**."
    ),
    items=tuple(
        Item(id=f"who5_{n}", number=n, text=text, options=WHO5_OPTIONS)
        for n, text in enumerate(_WHO5_TEXTS, start=1)
    ),
    source="WHO Regional Office for Europe - The DepCare Project (1998); Bech P., 2004",
)


# --------------------------------------------------------------------------
# Reduced Morningness/Eveningness Questionnaire (rMEQ)
# --------------------------------------------------------------------------
# Each item has its own response set and its own scoring key, taken verbatim
# from the score column of the source PDF.
RMEQ = Instrument(
    key="rmeq",
    name="Morningness/Eveningness Questionnaire",
    short_name="rMEQ",
    instructions="Select the response for each item that best describes you.",
    items=(
        Item(
            id="rmeq_1",
            number=1,
            text=(
                "Considering only your own “feeling best” rhythms, at what time "
                "would you get up if you were entirely free to plan your day?"
            ),
            options=(
                ("5 a.m. - 6:30 a.m.", 5),
                ("6:30 a.m. - 7:45 a.m.", 4),
                ("7:45 a.m. - 9:45 a.m.", 3),
                ("9:45 a.m. - 11 a.m.", 2),
                ("11 a.m. - 12 noon", 1),
            ),
        ),
        Item(
            id="rmeq_2",
            number=2,
            text=(
                "During the first half hour after awakening in the morning, how tired "
                "do you feel?"
            ),
            options=(
                ("Very tired", 1),
                ("Fairly tired", 2),
                ("Fairly refreshed", 3),
                ("Very refreshed", 4),
            ),
        ),
        Item(
            id="rmeq_3",
            number=3,
            text="At what time in the evening do you feel tired and in need of sleep?",
            options=(
                ("8 p.m. - 9 p.m.", 5),
                ("9 p.m. - 10:15 p.m.", 4),
                ("10:15 p.m. - 12:30 a.m.", 3),
                ("12:30 a.m. - 1:45 a.m.", 2),
                ("1:45 a.m. - 3 a.m.", 1),
            ),
        ),
        Item(
            id="rmeq_4",
            number=4,
            text=(
                "At what time of the day do you think that you reach your "
                "“feeling best” peak?"
            ),
            options=(
                ("10 p.m. - 5 a.m.", 1),
                ("5 p.m. - 10 p.m.", 2),
                ("10 a.m. - 5 p.m.", 3),
                ("8 a.m. - 10 a.m.", 4),
                ("5 a.m. - 8 a.m.", 5),
            ),
        ),
        Item(
            id="rmeq_5",
            number=5,
            text=(
                "One hears about “morning” and “evening” types of "
                "people. Which one of these types do you consider yourself to be?"
            ),
            options=(
                ("Definitely a “morning” type", 6),
                ("Rather more a “morning” than “evening” type", 4),
                ("Rather more an “evening” than “morning” type", 2),
                ("Definitely an “evening” type", 0),
            ),
        ),
    ),
    source="Adan & Almirall (1991)",
    shared_scale=False,
)


# --------------------------------------------------------------------------
# Highly Sensitive Person Scale (HSPS)
# --------------------------------------------------------------------------
# "27 items that respondents rate on a 7-point Likert scale ranging from
#  1 (Not at all) to 7 (Extremely)"
HSPS_OPTIONS: tuple[tuple[str, int], ...] = tuple((str(n), n) for n in range(1, 8))
HSPS_ANCHORS = ("1 = Not at all", "7 = Extremely")

_HSPS_TEXTS = [
    "Are you easily overwhelmed by strong sensory input?",
    "Do you seem to be aware of subtleties in your environment?",
    "Do other people's moods affect you?",
    "Do you tend to be more sensitive to pain?",
    "Do you find yourself needing to withdraw during busy days, into bed or into a "
    "darkened room or any place where you can have some privacy and relief from "
    "stimulation?",
    "Are you particularly sensitive to the effects of caffeine?",
    "Are you easily overwhelmed by things like bright lights, strong smells, coarse "
    "fabrics, or sirens close by?",
    "Do you have a rich, complex inner life?",
    "Are you made uncomfortable by loud noises?",
    "Are you deeply moved by the arts or music?",
    "Does your nervous system sometimes feel so frazzled that you just have to go "
    "off by yourself?",
    "Are you conscientious?",
    "Do you startle easily?",
    "Do you get rattled when you have a lot to do in a short amount of time?",
    "When people are uncomfortable in a physical environment, do you tend to know "
    "what needs to be done to make it more comfortable (like changing the lighting "
    "or the seating)?",
    "Are you annoyed when people try to get you to do too many things at once?",
    "Do you try hard to avoid making mistakes or forgetting things?",
    "Do you make a point to avoid violent movies and TV shows?",
    "Do you become unpleasantly aroused when a lot is going on around you?",
    "Does being very hungry create a strong reaction in you, disrupting your "
    "concentration or mood?",
    "Do changes in your life shake you up?",
    "Do you notice and enjoy delicate or fine scents, tastes, sounds, works of art?",
    "Do you find it unpleasant to have a lot going on at once?",
    "Do you make it a high priority to arrange your life to avoid upsetting or "
    "overwhelming situations?",
    "Are you bothered by intense stimuli, like loud noises or chaotic scenes?",
    "When you must compete or be observed while performing a task, do you become so "
    "nervous or shaky that you do much worse than you would otherwise?",
    "When you were a child, did parents or teachers seem to see you as sensitive "
    "or shy?",
]

HSPS = Instrument(
    key="hsps",
    name="Highly Sensitive Person Scale (HSPS)",
    short_name="HSPS",
    instructions=(
        "Rate each item on a 7-point scale, where **1 = Not at all** and "
        "**7 = Extremely**. Answer according to the way you personally feel."
    ),
    items=tuple(
        Item(id=f"hsps_{n}", number=n, text=text, options=HSPS_OPTIONS)
        for n, text in enumerate(_HSPS_TEXTS, start=1)
    ),
    source="Aron, E. N., & Aron, A. (1997). APA PsycTests. https://doi.org/10.1037/t00299-000",
    anchors=HSPS_ANCHORS,
)


INSTRUMENTS: dict[str, Instrument] = {
    inst.key: inst for inst in (ASRS, PSS, WHO5, RMEQ, HSPS)
}

ALL_ITEM_IDS: list[str] = [
    item.id for inst in INSTRUMENTS.values() for item in inst.items
]


def get_item(item_id: str) -> Item:
    """Look up an item by its global id."""
    key = item_id.rsplit("_", 1)[0]
    return INSTRUMENTS[key].item(item_id)
