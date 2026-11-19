"""F24 call limits: a node that keeps calling tools is ended by the backend's recursion limit, and the error is not retried."""

import pytest
from langgraph.errors import GraphRecursionError

LOOKUP = [["lookup_revision", {"name": "alpha"}]]


@pytest.mark.feature("F24")
async def test_the_recursion_limit_ends_a_looping_node(harness, tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_CORE_LANGGRAPH_RECURSION_LIMIT", "6")
    h = harness({"lookup": [LOOKUP] * 20})
    with pytest.raises(GraphRecursionError):
        await h.nodes.run("lookup", {"name": "alpha"})
    played = sum(int(f.read_text()) for f in tmp_path.glob("scripts-*/*.progress.json"))
    assert played <= 3   # six steps are three model/tool rounds; nothing ran the unit again
