"""The wiring-matrix audit (MTX-1, MTX-2): every backend has an entry for each feature, and each feature it declares
`native` or `helper` has a conformance test that ran and passed (or failed as expected) for that backend in this session.

`RAN` and `DESELECTED` are filled by `conformance/conftest.py` as the session goes.
"""

from collections.abc import Mapping

from agent_core.contracts.matrix import Feature, Matrix
from agent_core.core import registry

RAN: set[tuple[str, str]] = set()   # (backend name, feature id) of each conformance test that passed or xfailed
DESELECTED: list[str] = []          # the node ids of the conformance tests this session left out


def problems(matrices: Mapping[str, Matrix], ran: set[tuple[str, str]]) -> list[str]:
    found = []
    for name, matrix in matrices.items():
        for feature in Feature:
            entry = matrix.get(feature)
            if entry is None:
                found.append(f"backend {name} has no entry for {feature.id}")
            elif entry.state in ("native", "helper") and (name, feature.id) not in ran:
                found.append(f"backend {name} declares {feature.id} {entry.state} but its conformance tests do not run")
    return found


def all_matrices() -> dict[str, Matrix]:
    """The matrix of each backend the registry names."""
    matrices = {}
    for name in registry.BACKENDS:
        cls, settings = registry.backend(name)
        matrices[name] = cls(settings()).features()
    return matrices
