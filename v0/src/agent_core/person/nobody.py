from agent_core.contracts.registry import register


@register("person", "nobody")
class Nobody:
    """No one is there: nothing is told, and a question has no answer."""

    async def tell(self, text: str) -> None:
        pass

    async def ask(self, question: str, label: str = "") -> str | None:
        return None
