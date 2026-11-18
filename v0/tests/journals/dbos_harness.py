"""One process with the `dbos` journal, as a sequence job would have it; the tests run it as a subprocess, because DBOS
is one per process and a crash must be a real process death. Prints one JSON line.

The walk is a toy: steps `1:a`, `2:b[1]`, `3:b[2]`, `4:c`. Each step appends a line to `--log`; `--crash STEP` ends the
process inside that step, and `--fail STEP` makes it raise.
"""

import argparse
import asyncio
import json
import os

from dbos import DBOS

from agent_core.core.registry import provider

MAIN: dict = {}


async def main(a) -> None:
    MAIN["loop"] = asyncio.get_running_loop()

    async def work(label: str) -> str:
        with open(a.log, "a") as f:
            f.write(json.dumps({"step": label, "pid": os.getpid(), "main_loop": asyncio.get_running_loop() is MAIN["loop"]}) + "\n")
        if label == a.crash:
            os._exit(3)
        if label == a.fail:
            raise RuntimeError(f"{label} broke")
        await asyncio.sleep(0)
        return label.upper()

    async def walk(steps, name, facts):
        first = await steps.step("a", lambda: work("a"))
        rest = [await slot.run(f"b[{n}]", lambda n=n: work(f"b[{n}]")) for n, slot in enumerate(steps.reserve(2), 1)]
        last = await steps.step("c", lambda: work("c"))
        return {"name": name, "facts": facts, "results": [first, *rest, last]}

    journal = provider("journal", "dbos")(a.db, "harness", a.id)
    out: dict = {}
    try:
        if a.mode == "start":
            out["result"] = await journal.start(a.id, walk, "toy", {"x": 1})
        elif a.mode == "resume":
            out["result"] = await asyncio.wait_for(journal.resume(a.id, walk), 60)
        else:
            out["result"] = await asyncio.wait_for(journal.rerun(a.id, a.source, a.step, walk), 60)
    except Exception as e:
        out["error"] = f"{type(e).__name__}: {e}"
    try:
        steps = await DBOS.list_workflow_steps_async(a.id)
        out["steps"] = [[s["function_id"], s["function_name"], s["output"]] for s in steps]
    except Exception as e:
        out["steps_error"] = f"{type(e).__name__}: {e}"
    await journal.close()
    print(json.dumps(out, default=repr))


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("mode", choices=["start", "resume", "rerun"])
    p.add_argument("--db", required=True)
    p.add_argument("--id", required=True)
    p.add_argument("--log", required=True)
    p.add_argument("--crash")
    p.add_argument("--fail")
    p.add_argument("--source", help="rerun: the run to fork")
    p.add_argument("--step", type=int, help="rerun: the step to run from")
    asyncio.run(main(p.parse_args()))
