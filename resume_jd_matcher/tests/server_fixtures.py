"""Shared fixtures for the server tests.

Deliberately NOT named `test_*`, so `unittest discover` does not collect it as a
test module.

Two things every server test needs, and neither may touch the network:

* a **stub LLM client**, so no API key is required and the test asserts on the
  exact payload the service decided to send;
* a **stub knowledge base**, so the semantic embedder is not loaded for a unit
  test (it costs seconds and an index lock), while `retrieve_for_jd` still runs
  its real code path.

Both stand in for `src/` objects at the boundary - the service code under test is
the real one, calling the real guards and the real abstention rule.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.llm.client import LLMResult  # noqa: E402
from src.retrieval.store import Retrieved, RetrievalResult  # noqa: E402
from server.schemas import RawField  # noqa: E402


class StubClient:
    """Stands in for `OpenRouterClient`.

    Keyed by task name. A value may be a dict or a callable taking
    `(stub_input, user_prompt)`, so a test can react to what the service actually
    sent - which is how the "passport number never reaches the prompt" test
    works.
    """

    def __init__(
        self,
        responses: dict[str, Any] | None = None,
        *,
        offline: bool = True,
        model: str = "unit-test-stub",
    ) -> None:
        self.offline = offline
        self.cfg = SimpleNamespace(model=model)
        self.responses = responses or {}
        self.calls: list[dict[str, Any]] = []

    def complete_json(
        self,
        *,
        system: str,
        user: str,
        task: str,
        stub_input: dict[str, Any] | None = None,
    ) -> LLMResult:
        self.calls.append(
            {
                "task": task,
                "system": system,
                "user": user,
                "stub_input": stub_input or {},
            }
        )
        content = self.responses.get(task, {})
        if callable(content):
            content = content(stub_input or {}, user)
        return LLMResult(
            content=content,
            mode="offline_stub" if self.offline else "live_api",
            model=self.cfg.model,
        )

    def prompts_for(self, task: str) -> list[str]:
        return [call["user"] for call in self.calls if call["task"] == task]


class StubKnowledgeBase:
    """A knowledge base whose top-1 score the test chooses."""

    def __init__(self, score: float = 0.85, hits: int = 3) -> None:
        self.score = score
        self.hit_count = hits
        self.queries: list[str] = []
        self.closed = False

    def retrieve(self, query: str, top_k: int | None = None, family: str | None = None) -> RetrievalResult:
        self.queries.append(query)
        built = [
            Retrieved(
                chunk_id=f"chunk_{index:03d}",
                text=f"reference note {index}",
                score=self.score if index == 0 else max(0.0, self.score - 0.1 * index),
                raw_similarity=0.5,
                source="test",
                family="generic",
            )
            for index in range(self.hit_count)
        ]
        return RetrievalResult(query=query, hits=built)

    def describe(self) -> dict[str, Any]:
        return {"chunks": self.hit_count, "store": {"backend": "stub"}, "embedder": {"backend": "stub"}}

    def close(self) -> None:
        self.closed = True


class StubKbProvider:
    """Stands in for `services.KnowledgeBaseProvider`."""

    def __init__(self, kb: StubKnowledgeBase | None = None, error: str | None = None) -> None:
        self._kb = kb
        self.error = error
        self.builds = 0

    def get(self) -> StubKnowledgeBase | None:
        if self._kb is None:
            return None
        self.builds += 1
        return self._kb

    def describe(self) -> dict[str, Any]:
        return {"available": self._kb is not None, "error": self.error}

    def close(self) -> None:
        if self._kb is not None:
            self._kb.close()


def field(label: str = "", **kwargs: Any) -> RawField:
    """A `RawField` with DOM-plausible defaults."""
    payload: dict[str, Any] = {
        "tag": "input",
        "type": "text",
        "name": "",
        "id": "",
        "label": label,
        "placeholder": "",
        "aria_label": "",
        "required": False,
        "max_length": None,
        "options": [],
        "help_text": "",
        "current_value": "",
        "selector": "",
    }
    payload.update(kwargs)
    return RawField(**payload)


def webform_payload(entries: dict[str, dict[str, Any]], **extra: Any) -> dict[str, Any]:
    """Build a `/generate` model response keyed by field_id.

    `entries` maps field_id -> {"value": str|None, "confidence": float, ...}.
    """
    fields = []
    for field_id, spec in entries.items():
        fields.append(
            {
                "field_id": field_id,
                "suggested_value": spec.get("value"),
                "source": spec.get("source", "personal_info.full_name"),
                "jd_relevance": spec.get("jd_relevance", ""),
                "confidence": spec.get("confidence", 0.9),
                "message": spec.get("message", ""),
            }
        )
    payload: dict[str, Any] = {
        "overall_suggestions": extra.pop("overall_suggestions", []),
        "risk_flags": extra.pop("risk_flags", []),
        "fields": fields,
    }
    payload.update(extra)
    return payload


#: A profile that exercises all four modules. Synthetic, obviously.
PROFILE: dict[str, Any] = {
    "personal_info": {
        "full_name": "Zhang Wei",
        "email": "zhang.wei@example.edu",
        "phone": "+65 9123 4567",
        "location": "Singapore",
        "github": "github.com/zhangwei",
    },
    "education": [
        {
            "school": "Nanyang Technological University",
            "degree": "Master of Science",
            "major": "Computer Science",
            "start": "2024",
            "end": "2026",
            "gpa": "4.5",
        }
    ],
    "internship": [
        {
            "employer": "Acme Corp",
            "title": "Data Analyst Intern",
            "start": "May 2025",
            "end": "Aug 2025",
            "summary": "Built dashboards with Python and SQL for the risk team.",
        }
    ],
    "projects": [
        {
            "name": "Resume Matcher",
            "summary": "A retrieval-augmented prototype written in Python.",
        }
    ],
}

ALL_MODULES = ["personal_info", "internship", "projects", "education"]

JD_TEXT = (
    "Machine Learning Intern at Acme Corp, Singapore.\n"
    "Requirements: Python, PyTorch, SQL.\n"
    "Nice to have: Docker, Kubernetes.\n"
    "You will build training pipelines and evaluate models."
)
