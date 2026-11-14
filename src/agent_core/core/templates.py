"""Fill a node's Markdown: settings, inputs, session values, working values and included fragments."""

import posixpath
import re
from collections.abc import Mapping

from agent_core.contracts.resources import ResourceSource

PLACEHOLDER = re.compile(r"\{\{\s*(settings|input|session|node)\.([\w-]+)\s*\}\}")
INCLUDE = re.compile(r"\{\{\s*include\s+([^\s}]+)\s*\}\}")


class TemplateError(Exception):
    """The message names the placeholder or include and the file it is written in."""


def render(
    text: str,
    *,
    file: str,
    settings: object | None,
    inputs: Mapping,
    session: Mapping,
    values: Mapping,
    resources: ResourceSource,
) -> str:
    """`file` is where `text` came from. Included paths are relative to the instance root.

    A value that is filled in is never read again as a template.
    """
    filled = {"input": (inputs, "not given"), "session": (session, "not set"), "node": (values, "not set")}

    def fill(match: re.Match, where: str) -> str:
        kind, name = match.groups()
        if kind == "settings":
            value = getattr(settings, name, None) if not name.startswith("_") else None
            if value is None or callable(value):
                raise TemplateError(f"unknown placeholder {{{{settings.{name}}}}} in {where}")
            return str(value)
        source, absent = filled[kind]
        return str(source[name]) if name in source else absent

    def expand(body: str, where: str, chain: tuple[str, ...]) -> str:
        out = []
        end = 0
        for found in INCLUDE.finditer(body):
            out.append(PLACEHOLDER.sub(lambda m: fill(m, where), body[end:found.start()]))
            out.append(include(posixpath.normpath(found.group(1)), where, chain))
            end = found.end()
        out.append(PLACEHOLDER.sub(lambda m: fill(m, where), body[end:]))
        return "".join(out)

    def include(path: str, where: str, chain: tuple[str, ...]) -> str:
        if path in chain:
            loop = [*chain[chain.index(path):], path]
            raise TemplateError(f"{path} includes itself ({' → '.join(posixpath.basename(p) for p in loop)})")
        try:
            fragment = resources.read(path)
        except (FileNotFoundError, ValueError) as e:
            raise TemplateError(f"cannot include `{path}` in {where}: {e}") from None
        return expand(fragment, path, (*chain, path))

    return expand(text, file, (posixpath.normpath(file),))
