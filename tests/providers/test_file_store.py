import pytest

from agent_core.core.registry import provider
from agent_core.stores.file import FileStore


def test_the_file_store_is_found_by_name():   # SS-4
    assert provider("store", "file") is FileStore


def test_a_saved_session_loads_as_it_was_saved(tmp_path):   # SS-3
    store = FileStore(tmp_path)
    saved = {"facts": {"a": [1, 2]}, "transcript": [{"user": "hi"}], "status": "open"}
    store.save("session-1", saved)
    loaded = store.load("session-1")
    assert loaded == saved
    loaded["facts"]["a"].append(3)
    assert saved["facts"]["a"] == [1, 2] and store.load("session-1") == saved
    assert (tmp_path / "session-1" / "session.json").is_file()


def test_a_session_never_saved_loads_as_none(tmp_path):
    assert FileStore(tmp_path).load("session-unknown") is None


def test_a_save_that_cannot_be_serialised_leaves_the_last_saved_state(tmp_path):
    store = FileStore(tmp_path)
    store.save("s", {"facts": {"a": 1}})
    with pytest.raises(TypeError):
        store.save("s", {"facts": {"a": object()}})
    assert store.load("s") == {"facts": {"a": 1}}   # the file is replaced only by a whole new one
