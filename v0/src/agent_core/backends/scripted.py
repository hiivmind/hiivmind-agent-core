"""A backend that plays a script instead of calling a model.

A script is a list of steps. A step is a list of `[name, args]` pairs, which is
one response's calls, or a string, which is the model saying that and making
no call.
"""

import json
import re
from pathlib import Path

from mountainash_settings import MountainAshBaseSettings
from pydantic_settings import SettingsConfigDict

from agent_core.contracts import Brief, EndRun, ModelResponse, NodeController, RunEnd, ToolCall
from agent_core.contracts.registry import register_backend

_PROCEDURE_LINE = re.compile(r"^# Procedure of the node that is running: `([^`]+)`\s*$", re.MULTILINE)


class ScriptedSettings(MountainAshBaseSettings):
    model_config = SettingsConfigDict(env_prefix="AGENT_CORE_SCRIPTED_")

    SCRIPTS: Path | None = None  # a directory holding <node>.json


def _node_of(brief: Brief) -> str:
    found = _PROCEDURE_LINE.search(brief.instructions)
    if found is None:
        raise ValueError("the instructions have no line `# Procedure of the node that is running: `<name>``")
    return found.group(1)


@register_backend("scripted", settings=ScriptedSettings)
class ScriptedBackend:
    def __init__(self, settings: ScriptedSettings | None = None, script: list | None = None):
        self._settings = settings
        self._script = script

    def _steps(self, brief: Brief) -> list:
        if self._script is not None:
            return self._script
        scripts = self._settings.SCRIPTS if self._settings is not None else None
        if scripts is None:
            raise ValueError("the scripted backend needs a script or the setting SCRIPTS (a directory of <node>.json)")
        return json.loads((Path(scripts) / f"{_node_of(brief)}.json").read_text())

    async def drive(self, brief: Brief, controller: NodeController) -> RunEnd:
        said = ""
        count = 0
        for step in self._steps(brief):
            if isinstance(step, str):
                await controller.responded(ModelResponse(step, (), None, None, None))
                said = step
                if await controller.stopped(step) is None:
                    return RunEnd(by_controller=False, said=said)
                continue
            said = ""
            calls = []
            for name, args in step:
                count += 1
                calls.append(ToolCall(f"scripted_{count}", name, args))
            await controller.responded(ModelResponse("", tuple(calls), None, None, None))
            for call in calls:
                if isinstance(await controller.handle(call), EndRun):
                    return RunEnd(by_controller=True, said="")
        return RunEnd(by_controller=False, said=said)

