from agent_core.core.registry import provider
from agent_core.stores.memory import MemoryStore


def test_a_session_nobody_saved_loads_as_none():
    assert MemoryStore().load("refresh#1") is None


def test_a_saved_state_loads_back_and_sessions_are_kept_apart():
    store = MemoryStore()
    store.save("a", {"session": {"x": 1}})
    store.save("b", {"session": {"x": 2}})
    assert store.load("a") == {"session": {"x": 1}} and store.load("b") == {"session": {"x": 2}}
    store.save("a", {"session": {"x": 3}})
    assert store.load("a") == {"session": {"x": 3}}


def test_the_store_keeps_its_own_copy():
    store = MemoryStore()
    state = {"session": {"items": [1]}}
    store.save("a", state)
    state["session"]["items"].append(2)
    store.load("a")["session"]["items"].append(3)
    assert store.load("a") == {"session": {"items": [1]}}


def test_the_store_is_found_by_name():
    assert provider("store", "memory") is MemoryStore
