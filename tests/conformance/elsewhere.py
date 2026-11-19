"""Run one sequence of the conformance instance in this process and let whatever ends the process end it.

Run as `elsewhere.py <instance.yaml> <backend> <runs> <sequence> <run id> <facts as JSON>`.
"""

import asyncio
import json
import sys
from pathlib import Path

import agent_core


async def main(instance: str, backend: str, runs: str, sequence: str, run_id: str, facts: str) -> None:
    async with agent_core.open(Path(instance), backend=backend, runs=Path(runs)) as harness:
        await harness.sequences.run(sequence, json.loads(facts), run_id=run_id)


if __name__ == "__main__":
    asyncio.run(main(*sys.argv[1:]))
