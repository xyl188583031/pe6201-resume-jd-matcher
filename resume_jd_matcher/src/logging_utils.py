"""Append-only run log (JSONL) plus a structural privacy guard.

Two rules the logger enforces so they cannot be forgotten at a call site:

* Nothing that looks like raw user text ever reaches the file. Text is
  replaced by a sha256 prefix and a character count. Job descriptions and
  resumes are user data (PS section 8, Risk 4), and the run log is on disk.
* Retrieved chunk ids go in with every output. That is the PS section 8
  Risk 2 mitigation: when retrieval goes wrong you can see *what* was
  retrieved instead of guessing.

`allow_raw_text=True` exists only for the synthetic evaluation set, which is
generated, not personal. It is opt-in and off by default.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable

from src import config


def text_fingerprint(text: str) -> dict[str, Any]:
    """A record that is auditable without storing the text itself."""
    return {
        "chars": len(text),
        "sha256_8": hashlib.sha256(text.encode("utf-8")).hexdigest()[:8],
    }


# Keys we refuse to serialise verbatim. Matched case-insensitively on the
# leaf key name; anything else is passed through.
_TEXT_LIKE_KEYS = {
    "resume_text",
    "jd_text",
    "text",
    "raw_text",
    "content",
    "prompt",
    "user_prompt",
    "completion",
    "response_text",
}


def _scrub(value: Any, allow_raw_text: bool) -> Any:
    if allow_raw_text:
        return value
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, val in value.items():
            if isinstance(val, str) and key.lower() in _TEXT_LIKE_KEYS:
                out[key] = text_fingerprint(val)
            else:
                out[key] = _scrub(val, allow_raw_text)
        return out
    if isinstance(value, list):
        return [_scrub(v, allow_raw_text) for v in value]
    return value


@dataclass
class RunRecord:
    """One condition x one case. Everything needed to re-check the metric."""

    run_id: str
    condition: str                       # "A" | "B" | "C"
    case_id: str
    job_family: str = ""
    variant: str = ""
    mode: str = "offline_stub"           # offline_stub | live_api
    model: str = ""

    # retrieval evidence
    retrieved_chunk_ids: list[str] = field(default_factory=list)
    # The component actually used for confidence: the TOP-1 calibrated score.
    # The top-4 mean is also logged, because the two disagree when a single
    # strong chunk sits behind three weak ones, and a reader should be able to
    # see that rather than take one number on trust.
    retrieval_similarity: float = 0.0
    retrieval_mean_similarity: float = 0.0

    # scoring + abstention
    llm_self_confidence: float = 0.0
    confidence: float = 0.0
    # Which components actually entered the combined score. Condition A has only
    # retrieval, condition B only the model, condition C both. Without this a
    # record showing `llm_self_confidence: 0.0` for condition A reads as "the
    # model said zero" rather than "there was no model", and the reader cannot
    # tell which formula produced the number in `confidence`.
    components_present: list[str] = field(default_factory=list)
    abstained: bool = False
    abstention_reason: str = ""

    # outputs to be scored
    jd_skills: list[str] = field(default_factory=list)
    top_skills: list[str] = field(default_factory=list)
    prefill: dict[str, str] = field(default_factory=dict)
    suggestions: list[str] = field(default_factory=list)

    # evidence for the fabrication check
    claimed_items: list[str] = field(default_factory=list)
    # Claims the fabrication guard removed before the user saw them. Separate
    # from claimed_items so both are countable: how many fabrications reached
    # the output, and how many the guard caught on the way.
    stripped_claims: list[str] = field(default_factory=list)

    # provenance / cost
    input_report: dict[str, Any] = field(default_factory=dict)
    usage: dict[str, Any] = field(default_factory=dict)
    latency_ms: int = 0
    errors: list[str] = field(default_factory=list)
    # Human-readable trace of anything the pipeline decided on the way through:
    # the fabrication guard stripping a claim, an injection pattern redacted, a
    # retrieval score below threshold. Without these the log shows only the
    # outcome, and an outcome that was *produced* by a guard looks identical to
    # one that fell out of the model - which is how a guard misfiring on every
    # live call stayed invisible in the first live run.
    notes: list[str] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)

    def to_json(self, allow_raw_text: bool = False) -> str:
        return json.dumps(_scrub(asdict(self), allow_raw_text), ensure_ascii=False)


class RunLogger:
    """Writes RunRecords to artifacts/runs.jsonl. One JSON object per line."""

    def __init__(
        self,
        path: Path | None = None,
        *,
        append: bool = True,
        allow_raw_text: bool | None = None,
    ) -> None:
        self.path = Path(path) if path else config.path("runs_log")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.append = append
        if allow_raw_text is None:
            allow_raw_text = bool(config.get("privacy", "log_raw_user_text", default=False))
        self.allow_raw_text = allow_raw_text
        self._count = 0

    def __enter__(self) -> "RunLogger":
        if not self.append and self.path.exists():
            self.path.unlink()
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def log(self, record: RunRecord) -> None:
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(record.to_json(self.allow_raw_text) + "\n")
        self._count += 1

    @property
    def count(self) -> int:
        return self._count

    def read_all(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        rows: list[dict[str, Any]] = []
        with self.path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    rows.append(json.loads(line))
        return rows


def summarise_chunk_ids(records: Iterable[RunRecord]) -> dict[str, int]:
    """How often each knowledge chunk was retrieved. Sanity-check material."""
    counts: dict[str, int] = {}
    for rec in records:
        for cid in rec.retrieved_chunk_ids:
            counts[cid] = counts.get(cid, 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: -kv[1]))
