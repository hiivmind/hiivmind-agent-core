import asyncio
import weakref

from agent_core.contracts.registry import register

_LOCKS: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Lock]" = weakref.WeakKeyDictionary()


def _terminal_lock() -> asyncio.Lock:
    """One lock for the process's terminal, kept for each event loop (a lock may not move between loops)."""
    loop = asyncio.get_running_loop()
    if loop not in _LOCKS:
        _LOCKS[loop] = asyncio.Lock()
    return _LOCKS[loop]


@register("person", "terminal")
class Terminal:
    """The person at this process's terminal."""

    async def tell(self, text: str) -> None:
        print(text, flush=True)

    async def ask(self, question: str, label: str = "") -> str | None:
        """One question at a time across the process: nodes running at once take turns while the others keep working."""
        async with _terminal_lock():
            try:
                return await asyncio.get_running_loop().run_in_executor(None, input, f"[{label}] {question}\n> ")
            except EOFError:  # nothing more can be read: nobody is there
                return None
