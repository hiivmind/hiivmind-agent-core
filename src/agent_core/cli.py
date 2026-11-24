"""The command line: `agent-core job <instance.yaml> <sequence>`, a client of the facade (JOB-14, FAC-4). Exit 0: the
sequence ended `done` or `stopped`; 1: it ended `failed` or the run raised; 2: the run could not start (JOB-17)."""

import argparse
import asyncio
import sys
from collections.abc import Sequence
from pathlib import Path

import agent_core


def _param(text: str) -> tuple[str, str]:
    key, equals, value = text.partition("=")
    if not equals or not key:
        raise argparse.ArgumentTypeError(f"`{text}` is not KEY=VALUE")
    return key, value


def _rerun_from(text: str) -> tuple[str, int]:
    run_id, colon, step = text.rpartition(":")
    if not colon or not run_id or not step.isdigit():
        raise argparse.ArgumentTypeError(f"`{text}` is not RUN_ID:STEP")
    return run_id, int(step)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agent-core")
    commands = parser.add_subparsers(dest="command", required=True)
    job = commands.add_parser("job", help="run a sequence of an instance")
    job.add_argument("instance", type=Path, help="the instance.yaml")
    job.add_argument("name", help="a sequence of the topology")
    job.add_argument("--settings", action="append", default=[], type=Path, metavar="FILE", help="a settings file; repeatable")
    job.add_argument("--param", action="append", default=[], type=_param, metavar="KEY=VALUE", help="a setting; repeatable")
    job.add_argument("--no-ask", action="store_true", help="a question ends the node run even when a person is at the terminal")
    job.add_argument("--backend", help="the backend, instead of the instance's")
    job.add_argument("--run-dir", type=Path, help="default: <instance directory>/runs/<run id>/")
    job.add_argument("--input", action="append", default=[], type=_param, metavar="KEY=VALUE", help="a fact the sequence starts with; repeatable")
    again = job.add_mutually_exclusive_group()
    again.add_argument("--resume", metavar="RUN_ID", help="continue the sequence run RUN_ID from the steps that finished")
    again.add_argument("--rerun-from", type=_rerun_from, metavar="RUN_ID:STEP", help="a new run: RUN_ID's steps before STEP are replayed, the rest run")
    return parser


async def _job(args: argparse.Namespace) -> int:
    attended = sys.stdin is not None and sys.stdin.isatty() and not args.no_ask  # JOB-6
    run_dir = args.run_dir.resolve() if args.run_dir is not None else None
    runs = run_dir.parent if run_dir is not None else None
    run_id = args.resume or (run_dir.name if run_dir is not None else agent_core.new_run_id(args.name))
    try:
        async with agent_core.open(
            args.instance, backend=args.backend, settings=args.settings, params=dict(args.param),
            person="terminal" if attended else "nobody", runs=runs,
        ) as harness:
            if args.rerun_from:
                print(f"run {run_id} (from {args.rerun_from[0]}, step {args.rerun_from[1]})", flush=True)
                result = await harness.sequences.rerun(*args.rerun_from, new_run_id=run_id, name=args.name, run_dir=run_dir)
            else:
                print(f"run {run_id}", flush=True)
                if args.resume:
                    result = await harness.sequences.resume(args.resume, name=args.name, run_dir=run_dir)
                else:
                    result = await harness.sequences.run(args.name, dict(args.input), run_id=run_id)
    except agent_core.RunCannotStart as e:
        print(f"error: {e}", flush=True)
        return 2
    if result.end == "failed":
        print(f"error: sequence `{args.name}` ended failed: {result.summary}", flush=True)
    elif isinstance(result.summary, str):
        print(result.summary, flush=True)
    try:  # the record is written whole or not at all, and a value it cannot hold is named (Q7)
        (result.run_dir / "record.json").write_text(result.record.to_json())
    except (TypeError, OSError) as e:
        print(f"error: the run record of `{result.run_id}` cannot be written: {e}", flush=True)
        return 1
    return 1 if result.end == "failed" else 0


def main(argv: Sequence[str] | None = None) -> int:
    return asyncio.run(_job(_parser().parse_args(argv)))


if __name__ == "__main__":
    sys.exit(main())
