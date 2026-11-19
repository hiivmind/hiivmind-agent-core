from agent_core.contracts.matrix import Feature


def test_features_are_f1_to_f24_with_titles():
    assert [f.id for f in Feature] == [f"F{i}" for i in range(1, 25)]
    assert Feature.F3.title == "MCP"
    assert Feature.F22.title == "skills"
