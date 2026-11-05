"""Guard the design constraint: prompts stay concise.

The open-source rewrite keeps every prompt short and single-template; these
tests fail if anyone reintroduces verbose, mode-specific prompt sprawl.
"""
from __future__ import annotations

from jevrag import prompts

# Budgets in characters — generous headroom over today's sizes, but far below
# the multi-thousand-character prompts this release was rewritten against.
BUDGETS = {
    "PLANNER": 1200,
    "JEV": 1000,
    "SQL": 700,
    "GEOSPARQL": 900,
    "ONTOLOGY": 2800,
    "ANSWER": 700,
}


def test_all_prompts_present():
    assert set(BUDGETS) <= {n for n in dir(prompts) if n.isupper()}


def test_prompts_fit_budget():
    for name, budget in BUDGETS.items():
        text = getattr(prompts, name)
        assert len(text) <= budget, f"{name} is {len(text)} chars (budget {budget})"


def test_no_mode_variants():
    names = {n for n in dir(prompts) if n.isupper()}
    assert names == set(BUDGETS), f"unexpected prompt surface: {names}"


def test_placeholders_declared():
    assert "{schema}" in prompts.PLANNER and "{question}" in prompts.PLANNER
    assert "{schema}" in prompts.SQL and "{task}" in prompts.SQL
    assert "{profile}" in prompts.ONTOLOGY and "{tree_paths}" in prompts.ONTOLOGY
    assert "{question}" in prompts.ANSWER and "{evidence}" in prompts.ANSWER
