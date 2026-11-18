import os
from pathlib import Path


async def main(job):
    try:
        await job.call("web__fetch", {"url": "https://example.org/a"})
        first = "nothing was raised"
    except Exception as e:
        first = f"{type(e).__name__}: {e}"
    (Path(os.environ["AGENT_CORE_RUN_DIR"]) / "web.up").touch()  # the server is put right; the next call connects again
    second = await job.call("web__fetch", {"url": "https://example.org/a"})
    third = await job.call("web__fetch", {"url": "https://example.org/b"})
    await job.call("tools__shell", {"command": "echo one"})
    await job.call("tools__shell", {"command": "echo two"})
    notes = [await job.call("web__note", {"text": "for web"}), await job.call("tools__note", {"text": "for tools"})]
    return {"first": first, "second": second, "third": third, "notes": notes}
