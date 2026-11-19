"""The wiring matrix of the LangGraph backend: one entry per feature, each naming its means.

Each task of the build turns the entries it carries out to `native` or `helper`; the rest are `not built` with the
task that will build them. F6, F17, F22 and F23 stand at the values they have for every backend; F10, F14 and F19 are
deferred.
"""

from agent_core.contracts.matrix import Entry, Feature, Matrix

_TASK = {
    Feature.F1: 2, Feature.F2: 2, Feature.F18: 2, Feature.F21: 2,
    Feature.F8: 4, Feature.F9: 4, Feature.F11: 4,
    Feature.F12: 5, Feature.F13: 5, Feature.F20: 5,
    Feature.F3: 6,
    Feature.F24: 7,
    Feature.F15: 8,
    Feature.F7: 9, Feature.F16: 9,
}
_FIXED = {
    Feature.F6: "sessions, step 7",
    Feature.F17: "sessions, step 7",
    Feature.F22: "reserved",
    Feature.F23: "deferred",
    Feature.F10: "deferred: no consumer in this delivery",
    Feature.F14: "deferred: no consumer in this delivery",
    Feature.F19: "deferred: no consumer in this delivery",
}

_NATIVE = {
    Feature.F1: "`create_agent`",
    Feature.F2: "`ToolNode` runs the tools after `after_model` reviews the response",
    Feature.F18: "the offered tools; `after_model` and `wrap_tool_call`",
    Feature.F4: "`BaseTool`, body core policy; LangChain injects `ToolRuntime` into the coroutine of a tool with a dict `args_schema`, so the spec's own schema is the one the model sees",
    Feature.F5: "the `node` graph-state channel; `ToolNode` applies the tools' `Command` updates when the step ends",
    Feature.F15: "LangChain callbacks and hooks, mapped to events; LangSmith by its own environment variables",
    Feature.F21: "the core builds the brief; the backend passes it as `system_prompt`",
}

FEATURES: Matrix = {
    feature: Entry("native", _NATIVE[feature]) if feature in _NATIVE
    else Entry("not built", _FIXED[feature] if feature in _FIXED else f"Plan 2, task {_TASK[feature]}")
    for feature in Feature
}
