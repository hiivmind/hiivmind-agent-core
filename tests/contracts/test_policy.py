from agent_core.contracts.policy import Ending, StateUpdate, merge


def _state():
    return {"inputs": {"a": 1}, "values": {}, "outputs": {}, "session": {}, "rejections": 0, "ending": None}


def test_merge_applies_each_part_and_counts_a_rejection():
    s = _state()
    t = merge(s, StateUpdate(inputs={"a": 2}, values={"v": 3}, outputs={"o": 4}, session={"o": 4}, rejected=True))
    assert t == {"inputs": {"a": 2}, "values": {"v": 3}, "outputs": {"o": 4}, "session": {"o": 4}, "rejections": 1,
                 "ending": None}
    assert s["inputs"] == {"a": 1}


def test_merge_sets_the_ending():
    s = _state()
    assert merge(s, StateUpdate(ending=Ending("done", {"x": 1})))["ending"] == {
        "outcome": "done", "outputs": {"x": 1}, "reason": None, "detail": {}}
