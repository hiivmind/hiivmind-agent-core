"""Node runs a test scripts, for walking the sequences fixture without a model or a backend."""

import inspect
from pathlib import Path

SEQUENCES = Path(__file__).resolve().parents[1] / "fixtures" / "sequences"
RESULTS = {
    "update-sources": {"outcome": "updated", "outputs": {"rescan_batches": ["b1", "b2", "b3"], "sources_updated": ["polars"]}},
    "scan": {"outcome": "done", "outputs": {"entries": ["e1"]}},
    "index": {"outcome": "done", "outputs": {"entries": ["e1", "e2"]}},
    "verify": {"outcome": "done", "outputs": {"drift": 0}},
    "publish": {"outcome": "published", "outputs": {"pr_url": "https://example.org/pr/1"}},
    "status": {"outcome": "stale", "outputs": {"refresh_needed": True}},
    "migrate": {"outcome": "done", "outputs": {"entry_count": 3}},
    "graph": {"outcome": "done", "outputs": {"result": "ok"}},
}


class Nodes:
    """A `run_node` that gives each node its result from `results`, and keeps (node, inputs) of each run.

    A result may be a function of the inputs, or a coroutine function of them; `_` in a keyword stands for `-`.
    """

    def __init__(self, **results):
        self.results = {**RESULTS, **{k.replace("_", "-"): v for k, v in results.items()}}
        self.runs: list[tuple[str, dict]] = []

    async def __call__(self, node: str, inputs: dict) -> dict:
        self.runs.append((node, inputs))
        result = self.results[node]
        if callable(result):
            result = result(inputs)
            if inspect.isawaitable(result):
                result = await result
        return result

    @property
    def names(self) -> list[str]:
        return [node for node, _ in self.runs]


def names(result: dict) -> list[str]:
    return [entry["name"] for entry in result["trail"]]
