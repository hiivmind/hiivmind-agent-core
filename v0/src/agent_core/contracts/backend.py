from typing import Protocol

from .controller import NodeController
from .values import Brief, RunEnd


class NodeDriver(Protocol):
    async def drive(self, brief: Brief, controller: NodeController) -> RunEnd: ...
