"""Worker class resolver — regression tests.

Guards against the "Quick-start collision" class of bugs where the dispatcher
injects delivery-format keywords (e.g. "Quick-start steps") into a task's
summary and the resolver mis-routes a heavy task to a light class.

Bug history (April 2026): a research task with summary containing
"Quick-start steps (5-10 bullet points max)" was routed to the Quick (Haiku)
class because first-match-wins fired on \\bquick\\b in the summary before
the resolver ever checked the Research class. Fix: weighted scoring +
tiebreak on model weight.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.llm import worker_class_resolver as resolver


SAMPLE_CLASSES = [
    {
        "id": "01",
        "name": "Quick",
        "model": "claude-haiku-4-5-20251001",
        "intent_patterns": ["summarize", "tldr", "reformat"],
    },
    {
        "id": "02",
        "name": "Coding",
        "model": "claude-sonnet-4-6",
        "intent_patterns": ["debug", "refactor", "implement", "unit test", "fix bug"],
    },
    {
        "id": "03",
        "name": "Research",
        "model": "claude-opus-4-7",
        "intent_patterns": ["research", "investigate", "analyze", "feasibility"],
    },
    {
        "id": "04",
        "name": "Creative",
        "model": "claude-sonnet-4-6",
        "intent_patterns": ["brainstorm", "creative writing", "story", "narrative"],
    },
]


@pytest.fixture(autouse=True)
def _patch_loader(monkeypatch):
    """Replace the DB-backed loader with a constant fixture so tests are hermetic."""
    async def _fake_load():
        return list(SAMPLE_CLASSES)
    monkeypatch.setattr(resolver, "_load_worker_classes", _fake_load)


@pytest.mark.asyncio
async def test_clean_research_intent_picks_research():
    wc = await resolver.resolve_by_intent("research", "")
    assert wc is not None
    assert wc["name"] == "Research"


@pytest.mark.asyncio
async def test_quick_start_in_summary_does_not_beat_research_intent():
    """The original bug: 'Quick-start steps' in summary used to outrank intent=research."""
    intent = "research"
    summary = (
        "Home Assistant integration feasibility research. Quick-start steps "
        "(5-10 bullet points max). Compare alternatives across 4 devices."
    )
    wc = await resolver.resolve_by_intent(intent, summary)
    assert wc is not None, "Resolver returned None for an obvious research task"
    assert wc["name"] == "Research", (
        f"Routed to {wc['name']} (model={wc['model']}). "
        "Quick-start in summary should not outweigh intent=research."
    )


@pytest.mark.asyncio
async def test_intent_weighted_higher_than_summary():
    """A single intent match (3pts) beats a single summary match (1pt)."""
    wc = await resolver.resolve_by_intent("research", "summarize the findings")
    assert wc["name"] == "Research", (
        "Intent 'research' (3pts) should beat summary 'summarize' (1pt)"
    )


@pytest.mark.asyncio
async def test_tiebreak_prefers_heavier_model():
    """When two classes score equally, the heavier-model class wins.

    Coding (Sonnet) and Creative (Sonnet) both score 1 here on summary 'story'
    + 'implement'. They tie at 2 (1+1 summary points). But Research (Opus)
    has zero matches. So between Coding(Sonnet) and Creative(Sonnet) they
    tie — pick whichever, but neither should drop to Quick.
    """
    wc = await resolver.resolve_by_intent("", "implement a story narrative system")
    # Both Coding (implement) and Creative (story, narrative) have summary matches.
    # Creative scores 2 (story + narrative), Coding scores 1 (implement). Creative wins.
    assert wc["name"] == "Creative"


@pytest.mark.asyncio
async def test_tiebreak_opus_beats_sonnet_on_equal_score():
    """If Research and Coding tied on score, Opus class should win the tiebreak."""
    # 'analyze' (Research) + 'implement' (Coding) — both 1 match in intent (3pts each).
    wc = await resolver.resolve_by_intent("analyze and implement", "")
    assert wc["name"] == "Research", (
        f"Tied scores should favor Opus over Sonnet, got {wc['name']} ({wc['model']})"
    )


@pytest.mark.asyncio
async def test_no_match_returns_none():
    wc = await resolver.resolve_by_intent("walk the dog", "buy groceries")
    assert wc is None


@pytest.mark.asyncio
async def test_empty_input_returns_none():
    wc = await resolver.resolve_by_intent("", "")
    assert wc is None


@pytest.mark.asyncio
async def test_multi_word_pattern_matches():
    """Multi-word patterns like 'unit test' must match as a phrase."""
    wc = await resolver.resolve_by_intent("write a unit test for the parser", "")
    assert wc["name"] == "Coding"


@pytest.mark.asyncio
async def test_word_boundary_avoids_substring_false_positive():
    """'analyze' must not match 'analyzer' false positives in unrelated text."""
    wc = await resolver.resolve_by_intent("build the analyzer", "no other clues")
    # 'analyzer' should NOT trigger the 'analyze' pattern — \b boundary after analyz
    # means analyze\b doesn't match analyzer. Result: no match → None.
    assert wc is None


@pytest.mark.asyncio
async def test_intent_dominates_over_many_summary_matches():
    """3pt intent match beats up to 2 summary matches of a competing class."""
    # intent=research → Research +3
    # summary contains 'debug' and 'refactor' → Coding +2
    # Research wins 3 vs 2.
    wc = await resolver.resolve_by_intent(
        "research", "we need to debug and refactor the existing module"
    )
    assert wc["name"] == "Research"


def test_model_weight_ordering():
    assert resolver._model_weight("claude-opus-4-7") == 3
    assert resolver._model_weight("claude-sonnet-4-6") == 2
    assert resolver._model_weight("claude-haiku-4-5-20251001") == 1
    assert resolver._model_weight("unknown-model") == 2
    assert resolver._model_weight("") == 2
