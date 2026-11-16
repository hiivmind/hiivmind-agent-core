"""The fan-out (design §4.3): one run of a node per item of a list."""

import asyncio

import pytest
from walking import Nodes, names

from agent_core.core.sequences import SequenceError


def fan(cap=None, over="batches"):
    """A one-step sequence `fan`: scan over `over`, into `scans`."""
    start = {"fan_out": "scan", "over": over, "as": "batch", "into": "scans"}
    if cap is not None:
        start["max_concurrency"] = cap
    return {"fan": {"description": "d", "start": start, "transitions": {"scan": {"done": "end", "failed": "end"}}}}


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
    assert [inputs["batch"] for _, inputs in nodes.runs] == [1, 2]
    assert result["end"] == "stopped" and names(result) == ["scan[1]", "scan[2]", "scan"]


async def test_a_tools_list_is_one_journalled_step(walk, tmp_path, monkeypatch):          # FAN-5, FAN-6
    monkeypatch.setenv("SEQ_STALE", '["s1", "s2", "s3"]')
    nodes = Nodes()
    result = await walk("enrich", nodes=nodes)
    assert (tmp_path / "stale_batches.calls").read_text().count("\n") == 1
    assert result["trail"][0] == {"step": 1, "name": "scan[list]", "outcome": "done"}
    assert [inputs["batch"] for node, inputs in nodes.runs if node == "scan"] == ["s1", "s2", "s3"]


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
    assert nodes.runs[-1] == ("index", {"scans": [{"entries": ["e1"]}, {"entries": ["e1"]}]})
