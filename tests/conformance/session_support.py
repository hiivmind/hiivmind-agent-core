"""What a session test needs: a person who replies from a list, and an empty session state."""

from agent_core.contracts.person import Question


class ScriptedPerson:
    """A person whose `ask` and `hear` take their replies in order from `replies`; a None, or no reply left, is a person who
    has gone. It keeps what it was told and asked, in order, in `seen`."""

    def __init__(self, replies=(), on_ask=None):
        self.replies, self.on_ask = list(replies), on_ask
        self.told: list[str] = []
        self.asked: list[Question] = []
        self.seen: list[tuple[str, str | None]] = []   # ("told" | "asked" | "heard", text)

    def _next(self) -> str | None:
        return self.replies.pop(0) if self.replies else None

    async def tell(self, text):
        self.told.append(text)
        self.seen.append(("told", text))

    async def ask(self, question):
        self.asked.append(question)
        self.seen.append(("asked", question.text))
        if self.on_ask is not None:
            self.on_ask(question)
        return self._next()

    async def hear(self):
        reply = self._next()
        self.seen.append(("heard", reply))
        return reply
