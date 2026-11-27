from agent_core.contracts.context import transcript_handover
from agent_core.contracts.values import Message


def test_the_transcript_becomes_a_hand_over():   # CTX-5, NODE-15
    handed = transcript_handover([
        {"user": "update polars"},
        {"agent": "Which sources?"},
        {"node": "update-sources", "inputs": {"sources": "polars"}, "outcome": "failed", "reason": "no network"},
        {"sequence": "refresh", "inputs": {}, "end": "done"},
    ])
    assert handed[:2] == (Message("user", "update polars"), Message("agent", "Which sources?"))
    node, sequence = handed[2:]
    assert node.kind == "user" and all(word in node.text for word in ("update-sources", "polars", "failed", "no network"))
    assert sequence.kind == "user" and all(word in sequence.text for word in ("refresh", "done"))


def test_a_hand_over_that_opens_with_the_agent_begins_with_a_user_note():   # design §8.3
    handed = transcript_handover([{"agent": "What would you like to do?"}, {"user": "status"}])
    assert [m.kind for m in handed] == ["user", "agent", "user"]
    assert handed[1:] == (Message("agent", "What would you like to do?"), Message("user", "status"))


def test_an_empty_transcript_hands_over_nothing():
    assert transcript_handover([]) == ()
