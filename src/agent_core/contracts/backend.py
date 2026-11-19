from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Protocol

from .matrix import Matrix
from .tools import ToolSource
from .unit import Unit, UnitResult


class Backend(Protocol):
    def features(self) -> Matrix: ...
    def servers(self, declared: Mapping[str, dict], root: Path) -> ToolSource: ...   # how this backend reaches tool servers
    async def run_node(self, unit: Unit) -> UnitResult: ...
    async def run_fragment(self, unit: Unit) -> UnitResult: ...
    async def close(self) -> None: ...
