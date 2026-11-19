"""Session-wide test ordering."""

import pytest


@pytest.hookimpl(trylast=True)
def pytest_collection_modifyitems(items):
    """The audit reads what the conformance tests did, so it runs after every other test."""
    items.sort(key=lambda item: item.path.name == "test_audit.py")   # a stable sort: only the audit moves
