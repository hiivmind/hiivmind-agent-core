"""The fan-out (design §4.3): one run of a node per item of a list."""

import asyncio
import dataclasses

import pytest
from walking import Nodes, names

from agent_core.contracts.errors import ProviderRefused, ProviderUnavailable, ToolServerError
from agent_core.contracts.topology import END, FanOut, SequenceDef, Step
from agent_core.contracts.walk import StepRef
from agent_core.helpers.walk import SequenceError


def fan(cap=4, over="batches"):
    """A one-step sequence `fan`: scan over `over`, into `scans`."""
    return {"fan": SequenceDef("fan", "d", FanOut("scan", over, "batch", "scans", cap), {}, (),
                               {"scan": {"done": END, "failed": END}})}


def by_item(**per_item):
    """A scan result for each batch: done with `entries: [batch]` unless `per_item` names the batch."""

    def result(inputs):
        batch = inputs["batch"]
        found = per_item.get(f"b{batch}")
        if isinstance(found, Exception):
            raise found
        return found or {"outcome": "done", "outputs": {"entries": [batch]}}

    return result


async def test_results_come_back_in_item_order(walk):                                     # FAN-3
    async def slower_first(inputs):
        await asyncio.sleep(0.05 * (4 - inputs["batch"]))
        return {"outcome": "done", "outputs": {"entries": [inputs["batch"]]}}

    result = await walk("fan", {"batches": [1, 2, 3]}, nodes=Nodes(scan=slower_first), sequences=fan())
    assert result["facts"]["scans"] == [{"entries": [1]}, {"entries": [2]}, {"entries": [3]}]
    assert result["trail"] == [
        {"step": 1, "name": "scan[1]", "outcome": "done"},
        {"step": 2, "name": "scan[2]", "outcome": "done"},
        {"step": 3, "name": "scan[3]", "outcome": "done"},
        {"step": None, "name": "scan", "outcome": "done"},
    ]


async def test_each_run_has_its_step_number_item_and_first_attempt(walk):                  # ORC-6
    nodes = Nodes()
    await walk("fan", {"batches": ["a", "b"]}, nodes=nodes, sequences=fan())
    assert sorted((ref.number, ref.item, ref.attempt, intent) for _, _, ref, intent in nodes.runs) == [
        (1, 1, 1, "start"), (2, 2, 1, "start")]


async def test_no_more_than_max_concurrency_at_once(walk):                                # FAN-1
    running, peaks = 0, []

    async def counted(inputs):
        nonlocal running
        running += 1
        peaks.append(running)
        await asyncio.sleep(0.01)
        running -= 1
        return {"outcome": "done", "outputs": {}}

    await walk("fan", {"batches": list(range(10))}, nodes=Nodes(scan=counted), sequences=fan(cap=2))
    assert max(peaks) == 2
    peaks.clear()
    await walk("fan", {"batches": list(range(10))}, nodes=Nodes(scan=counted), sequences=fan())
    assert max(peaks) == 4


async def test_a_failed_run_is_kept_with_its_reason_and_the_rest_carry_on(walk):         # FAN-3, FAN-4
    nodes = Nodes(scan=by_item(b2={"outcome": "failed", "outputs": {"reason": "unreadable"}}))
    result = await walk("fan", {"batches": [1, 2, 3]}, nodes=nodes, sequences=fan())
    assert result["facts"]["scans"] == [{"entries": [1]}, {"entries": [3]}]
    assert result["facts"]["scans_failures"] == [{"item": 2, "outcome": "failed", "reason": "unreadable"}]
    assert result["trail"][-1]["outcome"] == "done" and result["end"] == "done"


async def test_a_run_that_raises_is_a_failed_item(walk):                                 # §4.3
    nodes = Nodes(scan=by_item(b1=RuntimeError("the server died")))
    result = await walk("fan", {"batches": [1, 2]}, nodes=nodes, sequences=fan())
    assert result["facts"]["scans_failures"] == [{"item": 1, "outcome": "failed", "reason": "RuntimeError: the server died"}]
    assert result["facts"]["scans"] == [{"entries": [2]}]


def refused(times: int, then=None, error=ProviderUnavailable("RateLimitError: concurrent connections")):
    """A scan that raises `error` `times` times, then gives `then` (done by default) or raises it."""
    count = {"runs": 0}

    def result(inputs):
        count["runs"] += 1
        if count["runs"] <= times:
            raise error
        if isinstance(then, Exception):
            raise then
        return then or {"outcome": "done", "outputs": {"entries": [inputs["batch"]]}}

    return result, count


async def test_a_run_the_provider_refused_is_run_once_more_and_counts_as_done(walk):       # RTY-2, RTY-3
    scan, count = refused(1)
    result = await walk("fan", {"batches": [1]}, nodes=Nodes(scan=scan), sequences=fan())
    assert count["runs"] == 2 and result["facts"]["scans"] == [{"entries": [1]}] and result["facts"]["scans_failures"] == []
    assert result["trail"] == [{"step": 1, "name": "scan[1]", "outcome": "done"}, {"step": None, "name": "scan", "outcome": "done"}]


async def test_a_refused_item_is_run_once_more_fresh_after_the_pause(walk, monkeypatch):   # RTY-2, ORC-6
    slept = []
    real_sleep = asyncio.sleep

    async def sleep(seconds):
        slept.append(seconds)
        await real_sleep(0)

    monkeypatch.setattr(asyncio, "sleep", sleep)
    scan, _ = refused(1)
    calls = Nodes(scan=lambda i: scan(i) if i["batch"] == 2 else by_item()(i))
    await walk("fan", {"batches": [1, 2]}, nodes=calls, sequences=fan(), pause=7)
    assert calls.runs[-2] == ("scan", {"batch": 2}, StepRef(2, 2, 1), "start")
    assert calls.runs[-1] == ("scan", {"batch": 2}, StepRef(2, 2, 2), "fresh")
    assert slept == [7]


async def test_a_refusal_that_will_not_pass_is_not_run_again(walk):                       # MOD-4, MOD-5, example 4
    reason = "the provider refused: insufficient_quota (no credit)"
    scan, count = refused(1, error=ProviderRefused(reason))
    nodes = Nodes(scan=lambda i: scan(i) if i["batch"] == 2 else by_item()(i))
    result = await walk("fan", {"batches": [1, 2]}, nodes=nodes, sequences=fan())
    assert count["runs"] == 1
    assert result["facts"]["scans_failures"] == [{"item": 2, "outcome": "failed", "reason": reason}]
    assert result["facts"]["scans"] == [{"entries": [1]}]


async def test_a_second_refusal_fails_the_item_with_run_twice(walk):                       # RTY-5
    scan, count = refused(2)
    result = await walk("fan", {"batches": [1]}, nodes=Nodes(scan=scan), sequences=fan())
    [failure] = result["facts"]["scans_failures"]
    assert count["runs"] == 2 and failure["outcome"] == "failed"
    assert failure["reason"] == "ProviderUnavailable: RateLimitError: concurrent connections (run twice)"


async def test_a_run_that_exits_failed_is_not_run_again(walk):                             # RTY-4
    nodes = Nodes(scan={"outcome": "failed", "outputs": {"reason": "unreadable"}})
    await walk("fan", {"batches": [1]}, nodes=nodes, sequences=fan())
    assert nodes.names == ["scan"]


async def test_a_run_that_raises_another_error_is_not_run_again(walk):                     # RTY-2a
    def recursion(inputs):
        raise RuntimeError("Recursion limit of 120 reached")

    nodes = Nodes(scan=recursion)
    result = await walk("fan", {"batches": [1]}, nodes=nodes, sequences=fan())
    assert nodes.names == ["scan"]
    assert result["facts"]["scans_failures"][0]["reason"] == "RuntimeError: Recursion limit of 120 reached"


async def test_any_error_of_the_second_run_is_a_failure_of_the_item(walk):                 # RTY-5
    scan, _ = refused(1, then=ToolServerError("files", "list", "it is gone"))

    def by_batch(inputs):
        return scan(inputs) if inputs["batch"] == 1 else {"outcome": "done", "outputs": {"entries": [2]}}

    result = await walk("fan", {"batches": [1, 2]}, nodes=Nodes(scan=by_batch), sequences=fan())
    assert result["facts"]["scans_failures"] == [{
        "item": 1, "outcome": "failed",
        "reason": "ToolServerError: tool server `files` did not answer the call to `list`: it is gone (run twice)"}]
    assert result["facts"]["scans"] == [{"entries": [2]}]


async def test_every_run_failed_gives_failed(walk):                                      # FAN-4
    nodes = Nodes(scan={"outcome": "failed", "outputs": {"reason": "x"}})
    result = await walk("fan", {"batches": [1, 2]}, nodes=nodes, sequences=fan())
    assert result["trail"][-1] == {"step": None, "name": "scan", "outcome": "failed"} and result["end"] == "failed"


async def test_an_empty_list_gives_done_with_no_results(walk):                           # FAN-4
    nodes = Nodes()
    result = await walk("fan", {"batches": []}, nodes=nodes, sequences=fan())
    assert (result["end"], result["facts"]["scans"], result["facts"]["scans_failures"], nodes.runs) == ("done", [], [], [])


async def test_a_stop_in_one_run_ends_the_sequence(walk):                                # FAN-4, SEQ-7
    nodes = Nodes(scan=by_item(b2={"outcome": "stopped", "outputs": {}}))
    result = await walk("fan", {"batches": [1, 2, 3, 4]}, nodes=nodes, sequences=fan(cap=1))
    assert [inputs["batch"] for _, inputs in nodes.inputs] == [1, 2]
    assert result["end"] == "stopped" and names(result) == ["scan[1]", "scan[2]", "scan"]


async def test_a_tools_list_is_one_journalled_step(walk, tmp_path, monkeypatch):          # FAN-5, FAN-6
    monkeypatch.setenv("SEQ_STALE", '["s1", "s2", "s3"]')
    nodes = Nodes()
    result = await walk("enrich", nodes=nodes)
    assert (tmp_path / "stale_batches.calls").read_text().count("\n") == 1
    assert result["trail"][0] == {"step": 1, "name": "scan[list]", "outcome": "done"}
    assert [inputs["batch"] for node, inputs in nodes.inputs if node == "scan"] == ["s1", "s2", "s3"]


async def test_a_fan_out_over_a_missing_fact_fails_the_run(walk):                        # Review Focus 2
    with pytest.raises(SequenceError, match="`batches`"):
        await walk("fan", {}, sequences=fan())
    with pytest.raises(SequenceError, match="`batches`.*str"):
        await walk("fan", {"batches": "b1"}, sequences=fan())


async def test_refresh_runs_end_to_end(walk):                                            # SEQ-2, FAN-1
    result = await walk("refresh")
    assert names(result) == ["checks", "update-sources", "scan[1]", "scan[2]", "scan[3]", "scan", "index", "verify", "publish"]
    assert [e["step"] for e in result["trail"]] == [1, 2, 3, 4, 5, None, 6, 7, 8]
    assert result["end"] == "done" and result["summary"] == {"pr_url": "https://example.org/pr/1"}


async def test_enrich_starts_with_a_fan_out(walk):                                       # FAN-5
    nodes = Nodes()
    result = await walk("enrich", nodes=nodes)
    assert names(result) == ["scan[list]", "scan[1]", "scan[2]", "scan", "index"]
    assert nodes.inputs[-1] == ("index", {"scans": [{"entries": ["e1"]}, {"entries": ["e1"]}]})


async def test_a_fanned_out_run_is_run_like_any_other(walk):                             # JOB-6, ORC-4
    nodes = Nodes()
    await walk("refresh", nodes=nodes)
    assert [(name, ref.item) for name, _, ref, _ in nodes.runs] == [
        ("update-sources", 0), ("scan", 1), ("scan", 2), ("scan", 3), ("index", 0), ("verify", 0), ("publish", 0)]
