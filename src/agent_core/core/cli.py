"""The command line: `agent-core job <instance.yaml> <name>` (CORE-2). Exit 0: the job succeeded; 1: it failed; 2: the run could not start."""

import argparse
import asyncio
import sys
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from agent_core.core.job_runner import run_job


def _param(text: str) -> tuple[str, str]:
    key, equals, value = text.partition("=")
    if not equals or not key:
        raise argparse.ArgumentTypeError(f"`{text}` is not KEY=VALUE")
    return key, value


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agent-core")
    commands = parser.add_subparsers(dest="command", required=True)
    job = commands.add_parser("job", help="run a job of an instance")
    job.add_argument("instance", type=Path, help="the instance.yaml")
    job.add_argument("name", help="the job: the file jobs/<name>.py of the instance")
    job.add_argument("--settings", action="append", default=[], type=Path, metavar="FILE", help="a settings file; repeatable")
    job.add_argument("--param", action="append", default=[], type=_param, metavar="KEY=VALUE", help="a setting; repeatable")
    job.add_argument("--no-ask", action="store_true", help="a question ends the node run even when a person is at the terminal")
    job.add_argument("--backend", help="the backend, instead of the instance's")
    job.add_argument("--run-dir", type=Path, help="default: <instance directory>/runs/<job>-<UTC start>-<6 hex>/")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    run_dir = args.run_dir
    if run_dir is None:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        run_dir = args.instance.resolve().parent / "runs" / f"{args.name}-{stamp}-{uuid4().hex[:6]}"
    return asyncio.run(
        run_job(
            args.instance, args.name, settings_files=args.settings, params=dict(args.param), no_ask=args.no_ask,
            backend=args.backend, run_dir=run_dir,
        )
    )


if __name__ == "__main__":
    sys.exit(main())
