from importlib.resources import files


def test_engine_document_is_self_contained_and_has_its_sections():                         # ENG-1, ENG-4
    text = files("agent_core.assets").joinpath("ENGINE.md").read_text()
    assert "# Engine rules" in text and "## Inside a node" in text and "http" not in text
    for verb in ("exit", "ask", "state_set", "state_get", "load"): assert f"`{verb}(" in text
    assert "does not change while the run lasts" in text      # the procedure is filled once (TPL-4)
    assert "session:" in text and "node:" in text             # the state shape of §5.5, in YAML (ENG-2)


def test_engine_document_keeps_to_what_step_1a_runs():                                      # R9
    text = files("agent_core.assets").joinpath("ENGINE.md").read_text()
    assert "## Routing" not in text and "## Diversions" not in text and "`enter(" not in text
    assert text.index("# Engine rules") < text.index("## Inside a node")


def test_engine_document_lists_each_instance_slot_and_what_an_absent_one_means():           # ENG-8
    text = files("agent_core.assets").joinpath("ENGINE.md").read_text()
    slots = text[text.index("## Instance slots"):text.index("## Inside a node")]
    for slot in ("TOPOLOGY", "POLICY", "IMPROVISATION", "ROUTING_GUIDE", "CONFIRM"): assert f"`{slot}`" in slots
    for optional in ("IMPROVISATION", "ROUTING_GUIDE", "CONFIRM"):
        line = next(l for l in slots.splitlines() if f"`{optional}`" in l)
        assert "absent" in line, optional


def test_procedure_conventions_name_each_convention():                                     # ENG-9a
    text = files("agent_core.assets").joinpath("PROCEDURES.md").read_text()
    conventions = {
        "phases": "## Phase", "steps": "numbered steps", "verb calls": "**CALL.**", "ASK alone": "ASK, ENTER and EXIT stand alone",
        "ENTER": "`ENTER <node>`", "EXIT": "**EXIT.**", "conditionals": "If ...", "go to step": "go to step",
        "display templates": "DISPLAY", "validation": "VALIDATE", "error tables": "error table", "inputs not given": "not given",
    }
    for name, marker in conventions.items(): assert marker in text, name
    assert "Do this once only" not in text
