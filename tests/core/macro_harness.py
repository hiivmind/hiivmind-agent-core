"""A process that starts a run with the `dbos` journal and the toy backend; the toy ends the process inside `--die-in`.
Run as `macro_harness.py <journal file> <run id> <log> <sequence> --die-in <unit>`."""

import argparse
import asyncio

from macro_support import Toy, make_unit, no_check, no_tool, topology

from agent_core.core.registry import provider
from agent_core.core.macro import Macro


async def main(a) -> None:
    topo, toy = topology(), Toy(a.log, a.die_in)
    journal = provider("journal", "dbos")(a.db, "macro", a.id)
    macro = Macro(topo, backends=lambda name: toy, default_backend="toy", make_unit=make_unit(topo),
                  journal=journal, call_tool=no_tool, check=no_check)
    await macro.start(a.id, a.sequence, {})
    await journal.close()


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("db")
    p.add_argument("id")
    p.add_argument("log")
    p.add_argument("sequence")
    p.add_argument("--die-in")
    asyncio.run(main(p.parse_args()))
