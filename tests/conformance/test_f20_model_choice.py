"""F20 model choice: the setting `MODEL=provider:model` picks the provider module and the model it is given.

Offline the observable is a provider module of the test's own: it is given the model's name, as the setting says it.
"""

from pathlib import Path

import pytest
from script_model import ScriptChatModel, ScriptProvider

from agent_core.contracts.errors import RunCannotStart
from agent_core.contracts.registry import register

LOOKUP = [["lookup_revision", {"name": "alpha"}]]
EXIT = [["exit", {"outcome": "done", "outputs": {}}]]
GIVEN: list[str] = []


class Naming(ScriptProvider):
    name = "naming"

    def chat_model(self, model: str, settings):
        GIVEN.append(model)
        return ScriptChatModel(directory=Path(self.directory))


register("model_provider", "naming")(Naming())


@pytest.mark.feature("F20")
async def test_the_setting_names_the_provider_and_the_model_it_is_given(harness):
    GIVEN.clear()
    h = harness({"lookup": [LOOKUP, EXIT]}, provider="naming:big-model-7")
    outcome = await h.nodes.run("lookup", {"name": "alpha"})
    assert (outcome.exit, GIVEN) == ("done", ["big-model-7"])


@pytest.mark.feature("F20")
async def test_a_setting_that_names_no_provider_stops_the_run_before_it_starts(harness):
    with pytest.raises(RunCannotStart, match="provider:model"):
        harness({"lookup": [EXIT]}, provider="nobody:model")
