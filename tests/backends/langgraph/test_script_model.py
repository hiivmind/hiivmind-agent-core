import json
import sys
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "conformance"))
from script_model import ScriptChatModel, ScriptRefusal  # noqa: E402

from agent_core.backends.langgraph.providers import provider_module  # noqa: E402
from agent_core.backends.langgraph.settings import LangGraphSettings  # noqa: E402

BRIEF = SystemMessage("The node's procedure.\n")   # the model reads its node from the run config, not the brief (CD-13)
NODE = {"metadata": {"agent_core_node": "n"}}


def model_of(tmp_path, steps):
    (tmp_path / "n.json").write_text(json.dumps(steps))
    return ScriptChatModel(directory=tmp_path)


def ask(model, conversation, first="one"):
    """One model call over the conversation; the answer joins it. A refusal is returned as its kind."""
    messages = [BRIEF, HumanMessage(first, id=first), *conversation]
    try:
        answer = model.invoke(messages, config=NODE)
    except ScriptRefusal as e:
        return e.kind
    conversation.append(answer)
    return answer


def test_the_script_provider_is_usable_through_provider_module(tmp_path):
    module, name = provider_module(f"script:{tmp_path}")
    settings = LangGraphSettings(MODEL=f"script:{tmp_path}")
    model = module.chat_model(name, settings)
    assert isinstance(model, ScriptChatModel)
    assert module.classify(ScriptRefusal("passes"), settings) == "passes"
    assert module.classify(ValueError(), settings) == "other"
    assert module.middleware(settings) == []
    message = AIMessage("x", usage_metadata={"input_tokens": 5, "output_tokens": 1, "total_tokens": 6, "input_token_details": {"cache_read": 2}})
    usage = module.usage(message)
    assert (usage.sent, usage.cache_read, usage.cache_written) == (5, 2, None)
    assert "refused" in module.refusal(ScriptRefusal("will not pass"), settings)


def test_two_interleaved_conversations_each_consume_their_own_refusals(tmp_path):
    model = model_of(tmp_path, [{"raise": "passes"}, {"raise": "passes"}, "answer"])
    a, b = [], []
    assert ask(model, a, "a") == "passes"
    assert ask(model, b, "b") == "passes"
    assert ask(model, a, "a") == "passes"
    assert ask(model, b, "b") == "passes"
    assert ask(model, a, "a").text == "answer"
    assert ask(model, b, "b").text == "answer"


def test_a_fresh_conversation_starts_at_the_first_step(tmp_path):
    model = model_of(tmp_path, [{"raise": "passes"}, "answer"])
    assert ask(model, [], "a") == "passes"
    assert ask(model, [], "a").text == "answer"
    assert ask(model, [], "fresh") == "passes"


def test_a_crash_is_played_once_and_a_raise_before_it_is_not_replayed_after_resume(tmp_path):
    steps = [{"raise": "passes"}, {"crash": True}, "answer"]
    first = model_of(tmp_path, steps)
    conversation = []
    assert ask(first, conversation) == "passes"
    with pytest.raises(SystemExit):
        ask(first, conversation)
    resumed = ScriptChatModel(directory=tmp_path)   # a rebuilt model, in effect another process
    assert ask(resumed, conversation).text == "answer"


def test_handed_over_answers_are_not_script_progress(tmp_path):
    model = model_of(tmp_path, [[["lookup_revision", {"name": "a"}]], "done"])
    handed = [HumanMessage("earlier", id="h"), AIMessage("an earlier answer"), HumanMessage("go", id="g")]
    answer = model.invoke([BRIEF, *handed], config=NODE)
    assert answer.tool_calls[0]["name"] == "lookup_revision"


def test_the_same_messages_under_two_thread_ids_each_get_the_refusal_first(tmp_path):
    model = model_of(tmp_path, [{"raise": "passes"}, "answer"])
    messages = [BRIEF, HumanMessage("same", id="same")]
    for thread in ("A", "B"):
        with pytest.raises(ScriptRefusal):
            model.invoke(messages, config={"configurable": {"thread_id": thread}, **NODE})
    assert model.invoke(messages, config={"configurable": {"thread_id": "A"}, **NODE}).text == "answer"


def test_the_model_finds_its_node_in_the_run_config(tmp_path):                            # CD-13
    model = model_of(tmp_path, ["played n"])
    assert model.invoke([BRIEF, HumanMessage("go", id="g")], config=NODE).text == "played n"
    with pytest.raises(ValueError, match="agent_core_node"):
        model.invoke([BRIEF, HumanMessage("go", id="g")])
