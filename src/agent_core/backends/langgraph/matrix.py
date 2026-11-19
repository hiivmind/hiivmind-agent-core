"""The wiring matrix of the LangGraph backend: one entry per feature, each naming its means.

Each task of the build turns the entries it carries out to `native` or `helper`; the rest are `not built` with the
task that will build them. F6, F17, F22 and F23 stand at the values they have for every backend; F10, F14 and F19 are
deferred.
"""

from agent_core.contracts.matrix import Entry, Feature, Matrix

_TASK = {
    Feature.F1: 2, Feature.F2: 2, Feature.F18: 2, Feature.F21: 2,
    Feature.F4: 3, Feature.F5: 3,
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

FEATURES: Matrix = {
    feature: Entry("not built", _FIXED[feature] if feature in _FIXED else f"Plan 2, task {_TASK[feature]}")
    for feature in Feature
}
