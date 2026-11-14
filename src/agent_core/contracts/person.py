from typing import Protocol


class Person(Protocol):
    async def tell(self, text: str) -> None: ...
    async def ask(self, question: str, label: str = "") -> str | None: ...  # None: nobody is there
