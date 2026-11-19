"""The wiring matrix of the LangGraph backend: one entry per feature, each naming its means.

Each task of the build turns the entries it carries out to `native` or `helper`; the rest are `not built` with the
task that will build them. F6, F17, F22 and F23 stand at the values they have for every backend; F10, F14 and F19 are
deferred.
"""

from agent_core.contracts.matrix import Entry, Feature, Matrix

_TASK = {
    Feature.F1: 2, Feature.F2: 2, Feature.F18: 2, Feature.F21: 2,
    Feature.F7: 9, Feature.F16: 9,
}
_FIXED = {
    Feature.F6: "sessions, step 7",
    Feature.F17: "sessions, step 7",
    Feature.F22: "reserved",
    Feature.F23: "deferred",
    Feature.F10: "deferred: no setting turns it on yet; the SDK summarizer's own retries would be a second retry owner (MOD-6)",
    Feature.F14: "deferred: `models.usage` has no consumer in this delivery; the record's token counts come from the provider module's `usage` (SCOPE-7)",
    Feature.F19: "deferred: no consumer in this delivery",
}

_HELPER = {
    Feature.F8: "a synchronous person inside the call; `interrupt` is not used in a job",
    Feature.F9: "the `none` strategy; calls handed over as calls (`_render`)",
    Feature.F11: "the `exit` tool, core policy: LangChain's structured output has the wrong shape for a union of exits, retries without a budget and validates before recorded outputs merge (architecture §4.4)",
}
_NATIVE = {
    Feature.F1: "`create_agent`",
    Feature.F2: "`ToolNode` runs the tools after `after_model` reviews the response",
    Feature.F18: "the offered tools; `after_model` and `wrap_tool_call`",
    Feature.F3: "`langchain-mcp-adapters`: one `MultiServerMCPClient` session per server for a run, its tools loaded over it by `load_mcp_tools`; every call goes through core policy to that session",
    Feature.F4: "`BaseTool`, body core policy; LangChain injects `ToolRuntime` into the coroutine of a tool with a dict `args_schema`, so the spec's own schema is the one the model sees",
    Feature.F5: "the `node` graph-state channel; `ToolNode` applies the tools' `Command` updates when the step ends",
    Feature.F12: "`ModelRetryMiddleware` with the provider's classifier; client retries off",
    Feature.F13: "the provider module's cache middleware",
    Feature.F20: "`init_chat_model` through the provider module",
    Feature.F15: "LangChain callbacks and hooks, mapped to events; LangSmith by its own environment variables",
    Feature.F24: "`recursion_limit`",
    Feature.F21: "the core builds the brief; the backend passes it as `system_prompt`",
}

FEATURES: Matrix = {
    feature: Entry("native", _NATIVE[feature]) if feature in _NATIVE
    else Entry("helper", _HELPER[feature]) if feature in _HELPER
    else Entry("not built", _FIXED[feature] if feature in _FIXED else f"Plan 2, task {_TASK[feature]}")
    for feature in Feature
}
