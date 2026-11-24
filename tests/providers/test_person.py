import asyncio
import io
import threading
import time

from agent_core.contracts.person import Question
from agent_core.core.registry import provider
from agent_core.person.nobody import Nobody
from agent_core.person.terminal import Terminal


def test_both_persons_are_found_by_name():
    assert provider("person", "nobody") is Nobody and provider("person", "terminal") is Terminal


async def test_nobody_tells_nothing_and_answers_none(capsys):                              # JOB-6
    person = Nobody()
    assert await person.tell("hello") is None
    assert await person.ask(Question("Which?", "refresh", 1, {})) is None
    assert capsys.readouterr().out == ""


async def test_terminal_tells_by_printing(capsys):
    await Terminal().tell("updating polars")
    assert capsys.readouterr().out == "updating polars\n"


async def test_terminal_asks_with_the_node_its_number_and_reads_one_line(monkeypatch, capsys):   # JOB-6
    monkeypatch.setattr("sys.stdin", io.StringIO("polars\nibis\n"))
    assert await Terminal().ask(Question("Which sources?", "refresh", 2, {})) == "polars"
    assert capsys.readouterr().out == "[refresh#2] Which sources?\n> "   # no trailing space with no inputs (Review Focus 4)


async def test_the_terminal_shows_the_inputs_of_the_run_after_its_label(monkeypatch):            # E12, RP-8
    monkeypatch.setattr("builtins.input", lambda prompt: prompt)
    assert await Terminal().ask(Question("Which branch?", "scan", 3, {"sources": "polars"})) == "[scan#3 polars] Which branch?\n> "


async def test_terminal_with_no_input_left_is_nobody_there(monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO(""))
    assert await Terminal().ask(Question("Which?", "refresh", 1, {})) is None


async def test_terminal_puts_one_question_at_a_time(monkeypatch):                           # JOB-6
    inside, most = 0, 0
    lock = threading.Lock()

    def slow_input(prompt=""):
        nonlocal inside, most
        with lock:
            inside += 1
            most = max(most, inside)
        time.sleep(0.05)
        with lock:
            inside -= 1
        return prompt

    monkeypatch.setattr("builtins.input", slow_input)
    person = Terminal()
    answers = await asyncio.gather(*(person.ask(Question(f"q{n}", "node", n, {})) for n in range(3)))
    assert most == 1 and answers == [f"[node#{n}] q{n}\n> " for n in range(3)]
