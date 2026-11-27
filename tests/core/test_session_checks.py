"""The checks a session makes on the topology when it starts, and not when the instance loads (SS-12, E10)."""

from pathlib import Path

import pytest
from support import load

from agent_core.contracts.errors import RunCannotStart
from agent_core.core.session import check_topology

CONFORMANCE = Path(__file__).resolve().parents[1] / "conformance" / "instance"


def test_a_session_refuses_improvisation_until_diversions_are_built(instance):   # E10
    with pytest.raises(RunCannotStart) as refused:
        check_topology(instance)
    assert str(refused.value) == "topology.yaml: improvisation is on, and diversions are not built yet (backlog 48)"


def test_an_exit_handling_other_than_route_or_end_is_refused(broken):
    broken("topology.yaml", (broken.root / "topology.yaml").read_text().replace("  done: route", "  done: stop"))
    with pytest.raises(RunCannotStart, match=r"^topology\.yaml: .*`done`.*`stop`"):
        check_topology(load(broken.root))


def test_a_menu_item_that_names_nothing_is_refused(broken):
    text = (broken.root / "topology.yaml").read_text().replace("{label: Status, node: status}", "{label: Ghost, node: ghost}")
    broken("topology.yaml", text)
    with pytest.raises(RunCannotStart, match=r"^topology\.yaml: .*`Ghost`.*`ghost`"):
        check_topology(load(broken.root))


def test_the_corpus_shaped_topology_passes():
    check_topology(load(CONFORMANCE))
