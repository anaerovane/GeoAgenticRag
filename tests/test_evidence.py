"""Evidence tree: observations survive pruning and deduplicate."""
from __future__ import annotations

from jevrag.evidence import EvidenceTree
from jevrag.tree import BranchResult, Node


def _node(nid="n1"):
    return Node(id=nid, query="q", tool="sql")


def _result(items):
    return BranchResult(status="success", summary="ok", evidence=items)


class TestAttach:
    def test_assigns_sequential_ids(self):
        ev = EvidenceTree()
        added = ev.attach(_node(), _result([
            {"source": "sql", "text": "a"}, {"source": "sql", "text": "b"}]))
        assert [e.id for e in added] == ["e1", "e2"]
        assert ev.to_dict()["count"] == 2

    def test_deduplicates_identical_text(self):
        ev = EvidenceTree()
        ev.attach(_node(), _result([{"source": "sql", "text": "same line"}]))
        added = ev.attach(_node(), _result([{"source": "sql", "text": "same line"}]))
        assert added == []
        assert len(ev.items) == 1

    def test_skips_blank_text(self):
        ev = EvidenceTree()
        assert ev.attach(_node(), _result([{"source": "sql", "text": "  "}])) == []

    def test_respects_cap(self):
        ev = EvidenceTree(max_items=2)
        added = ev.attach(_node(), _result([
            {"source": "sql", "text": t} for t in "abcd"]))
        assert len(added) == 2
        assert len(ev.items) == 2

    def test_items_from_pruned_branches_stay(self):
        # Attach under a node, then "prune" — attach() never removes items.
        ev = EvidenceTree()
        ev.attach(_node("n1"), _result([{"source": "sql", "text": "kept"}]))
        ev.attach(_node("n2"), _result([{"source": "search", "text": "also kept"}]))
        assert [e.id for e in ev.items] == ["e1", "e2"]

    def test_payload_round_trip(self):
        ev = EvidenceTree()
        ev.attach(_node(), _result([
            {"source": "sql", "text": "row", "payload": {"row_count": 1}}]))
        item = ev.to_dict()["items"][0]
        assert item["payload"] == {"row_count": 1}


class TestPrompt:
    def test_citation_lines(self):
        ev = EvidenceTree()
        ev.attach(_node("n1"), _result([{"source": "sql", "text": "Cedar Park"}]))
        assert ev.to_prompt() == "[e1] (sql, node n1) Cedar Park"

    def test_placeholder_when_empty(self):
        assert EvidenceTree().to_prompt() == "[e1] (none) no evidence collected"
