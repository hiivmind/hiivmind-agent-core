"""Session-wide test ordering, and the run directory the fixture instances' own functions and checks read."""

import pytest


@pytest.hookimpl(trylast=True)
def pytest_collection_modifyitems(items):
    """The audit reads what the conformance tests did, so it runs after every other test."""
    items.sort(key=lambda item: item.path.name == "test_audit.py")   # a stable sort: only the audit moves


@pytest.fixture(autouse=True)
def fixture_run_dir(tmp_path, monkeypatch):
    """The fixtures' functions and checks run in this process and write where `AGENT_CORE_RUN_DIR` says. The harness
    gives that variable to servers only (RP-1, Q5), so the tests set it for the fixtures themselves."""
    directory = tmp_path / "fixture-run"
    directory.mkdir()
    monkeypatch.setenv("AGENT_CORE_RUN_DIR", str(directory))
    return directory
