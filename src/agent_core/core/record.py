"""What is kept of each node run, for the record of a job (SCOPE-7)."""

from dataclasses import asdict, dataclass, field


@dataclass
class NodeRunNote:
    """One node run: where each part of its instructions came from and how long it was (in characters), the tools
    it was offered, the handover it was given, and what it cost.

    A count is None, "not known", as soon as one response of the run reports it as None; it is never read as zero.
    """

    label: str
    node: str
    parts: list[tuple[str, int]]
    tools: list[str]
    handover: list[str]
    model_calls: int = 0
    tokens_sent: int | None = 0
    cache_read: int | None = 0
    cache_written: int | None = 0


@dataclass
class RunRecord:
    """The record of a job (JOB-9a, SCOPE-7): what was asked, how it went, and what each node run did.

    `failures` holds each failed node run as `{"node": ..., ...the failed result}`, or `{"node": ..., "error": ...}` when
    a tool server could not be reached. `notes` is written as `runs`.
    """

    params: dict
    settings_files: list[str]
    backend: str
    attended: bool
    start: str
    job: str = ""
    end: str | None = None
    status: str | None = None          # `ok` or `failed`, set when the job ends
    summary: object = None             # what `main` returned, or the exception's `Type: message`
    failures: list[dict] = field(default_factory=list)
    notes: list[NodeRunNote] = field(default_factory=list)

    @property
    def model_calls(self) -> int:
        return sum(note.model_calls for note in self.notes)

    def as_dict(self) -> dict:
        return {
            "job": self.job,
            "params": self.params,
            "settings_files": self.settings_files,
            "backend": self.backend,
            "attended": self.attended,
            "start": self.start,
            "end": self.end,
            "status": self.status,
            "summary": self.summary,
            "failures": self.failures,
            "model_calls": self.model_calls,
            "runs": [asdict(note) for note in self.notes],
        }
