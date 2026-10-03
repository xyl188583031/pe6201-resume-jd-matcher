"""OpenRouter call wrapper.

Responsibilities, and nothing else:

* one place where the API key is handled (never logged, never written to disk)
* retries with backoff on transient failures
* strict JSON parsing with a repair step, because a stray markdown fence is a
  routine failure and should not become a silently dropped case
* token accounting and a *cost estimate* (PS section 5, ~$0.02-0.05/application)
* an offline mode that routes to a deterministic stub, so the harness and the
  unit tests run with no key and no network

The client reports `mode` on every result. Nothing downstream is allowed to
present offline-stub numbers as model behaviour.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from typing import Any

from src import config

OFFLINE_MODE = "offline_stub"
LIVE_MODE = "live_api"

_FENCE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.MULTILINE)
_TRAILING_COMMA = re.compile(r",\s*([}\]])")


class LLMError(RuntimeError):
    """Any failure that should surface as a failed case, not a crash."""


@dataclass
class LLMResult:
    content: dict[str, Any]
    mode: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    est_cost_usd: float = 0.0
    latency_ms: int = 0
    attempts: int = 1
    errors: list[str] = field(default_factory=list)

    @property
    def is_offline(self) -> bool:
        return self.mode == OFFLINE_MODE


def extract_json(raw: str) -> dict[str, Any]:
    """Parse model output into a dict, repairing the two usual defects.

    Raises LLMError if the payload is genuinely unusable - the caller turns
    that into a failed case with the raw text fingerprinted into the log.
    """
    if raw is None:
        raise LLMError("empty response")
    text = raw.strip()
    if not text:
        raise LLMError("empty response")

    if text.startswith("```"):
        text = _FENCE.sub("", text).strip()

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end <= start:
            raise LLMError(f"no JSON object in response (first 80 chars: {text[:80]!r})")
        candidate = text[start : end + 1]
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            try:
                parsed = json.loads(_TRAILING_COMMA.sub(r"\1", candidate))
            except json.JSONDecodeError as exc:
                raise LLMError(f"unparseable JSON: {exc}") from exc

    if not isinstance(parsed, dict):
        raise LLMError(f"expected a JSON object, got {type(parsed).__name__}")
    return parsed


def estimate_cost(prompt_tokens: int, completion_tokens: int, llm_cfg: config.LLMConfig) -> float:
    return (
        prompt_tokens / 1_000_000 * llm_cfg.price_in
        + completion_tokens / 1_000_000 * llm_cfg.price_out
    )


class OpenRouterClient:
    """`complete_json` is the only entry point the pipeline uses."""

    def __init__(
        self,
        api_key: str | None = None,
        *,
        force_offline: bool | None = None,
        cfg: config.LLMConfig | None = None,
    ) -> None:
        self.cfg = cfg or config.LLMConfig.load()
        self.api_key = api_key.strip() if api_key and api_key.strip() else config.api_key_from_env()
        if force_offline is None:
            force_offline = config.offline_forced()
        # No key -> offline. This is a deliberate design choice: the harness,
        # the tests and a fresh clone all work before anyone signs up for
        # anything. The mode is stamped on every record so it cannot be
        # mistaken for live output.
        self.offline = bool(force_offline or not self.api_key)
        self._client: Any = None
        self.calls = 0
        self.total_prompt_tokens = 0
        self.total_completion_tokens = 0
        self.total_est_cost_usd = 0.0

    # ------------------------------------------------------------------ setup

    def _lazy_client(self) -> Any:
        if self._client is not None:
            return self._client
        try:
            from openai import OpenAI
        except Exception as exc:  # pragma: no cover - openai is a hard requirement
            raise LLMError(f"openai package unavailable: {exc}") from exc
        self._client = OpenAI(
            base_url=self.cfg.base_url,
            api_key=self.api_key,
            timeout=self.cfg.timeout_s,
        )
        return self._client

    # ------------------------------------------------------------------ calls

    def complete_json(
        self,
        *,
        system: str,
        user: str,
        task: str,
        stub_input: dict[str, Any] | None = None,
    ) -> LLMResult:
        """One JSON-returning call.

        `task` selects the offline stub branch. `stub_input` carries the raw
        text the stub needs; it is ignored on the live path.
        """
        started = time.perf_counter()

        if self.offline:
            from src.llm.offline import run_stub

            content = run_stub(task, stub_input or {})
            elapsed = int((time.perf_counter() - started) * 1000)
            return LLMResult(
                content=content,
                mode=OFFLINE_MODE,
                model="offline-deterministic-stub",
                latency_ms=elapsed,
                errors=[],
            )

        errors: list[str] = []
        last_exc: Exception | None = None
        for attempt in range(1, self.cfg.max_retries + 2):
            try:
                response = self._lazy_client().chat.completions.create(
                    model=self.cfg.model,
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    response_format={"type": "json_object"},
                    temperature=self.cfg.temperature,
                    max_tokens=self.cfg.max_tokens,
                )
                raw = response.choices[0].message.content
                content = extract_json(raw)

                usage = getattr(response, "usage", None)
                prompt_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
                completion_tokens = int(getattr(usage, "completion_tokens", 0) or 0)
                cost = estimate_cost(prompt_tokens, completion_tokens, self.cfg)

                self.calls += 1
                self.total_prompt_tokens += prompt_tokens
                self.total_completion_tokens += completion_tokens
                self.total_est_cost_usd += cost

                return LLMResult(
                    content=content,
                    mode=LIVE_MODE,
                    model=self.cfg.model,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    est_cost_usd=cost,
                    latency_ms=int((time.perf_counter() - started) * 1000),
                    attempts=attempt,
                    errors=errors,
                )
            except Exception as exc:  # noqa: BLE001 - every failure becomes a case error
                last_exc = exc
                errors.append(f"attempt {attempt}: {type(exc).__name__}: {exc}")
                if attempt <= self.cfg.max_retries:
                    time.sleep(min(2 ** (attempt - 1), 8))

        raise LLMError(
            f"{task} failed after {self.cfg.max_retries + 1} attempts: {last_exc}"
        )

    # ------------------------------------------------------------- accounting

    def cost_summary(self) -> dict[str, Any]:
        return {
            "mode": OFFLINE_MODE if self.offline else LIVE_MODE,
            "model": "offline-deterministic-stub" if self.offline else self.cfg.model,
            "calls": self.calls,
            "prompt_tokens": self.total_prompt_tokens,
            "completion_tokens": self.total_completion_tokens,
            "est_cost_usd": round(self.total_est_cost_usd, 6),
            "note": (
                "offline mode makes no API calls; token and cost figures are zero by "
                "construction, not measured"
                if self.offline
                else "cost is an ESTIMATE from the price table in config.yaml, not an invoice"
            ),
        }
