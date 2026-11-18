from agent_core.core.registry import provider


async def test_none_runs_each_step_once():
    calls = []

    async def call(name):
        calls.append(name)
        return name.upper()

    async def walk(steps, name, facts):
        first = await steps.step("a", lambda: call("a"))
        reserved = steps.reserve(2)
        rest = [await r.run(f"b[{i}]", lambda i=i: call(f"b{i}")) for i, r in enumerate(reserved, 1)]
        return {"name": name, "facts": facts, "results": [first, *rest]}

    journal = provider("journal", "none")()
    result = await journal.start("run-1", walk, "seq", {"x": 1})
    await journal.close()
    assert calls == ["a", "b1", "b2"]
    assert result == {"name": "seq", "facts": {"x": 1}, "results": ["A", "B1", "B2"]}
