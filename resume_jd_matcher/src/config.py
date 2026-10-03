"""Configuration loader. YAML on disk + environment overrides.

Every module reads tunables through here so there is exactly one place to
change a threshold, a model name, or a path.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

try:  # optional: lets a local .env work without exporting anything
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # pragma: no cover - dotenv is a convenience, not a dependency
    pass

# repo root = .../resume_jd_matcher  (this file is src/config.py)
ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config.yaml"


class ConfigError(RuntimeError):
    """Raised when config.yaml is missing or malformed."""


def _load_yaml() -> dict[str, Any]:
    if not CONFIG_PATH.exists():
        raise ConfigError(f"config.yaml not found at {CONFIG_PATH}")
    with CONFIG_PATH.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if not isinstance(data, dict):
        raise ConfigError("config.yaml did not parse into a mapping")
    return data


_RAW = _load_yaml()


def raw() -> dict[str, Any]:
    """The whole parsed config. Exposed for the UI's debug panel."""
    return _RAW


def get(*keys: str, default: Any = None) -> Any:
    """Nested lookup: get("confidence", "abstention_threshold")."""
    node: Any = _RAW
    for key in keys:
        if not isinstance(node, dict) or key not in node:
            return default
        node = node[key]
    return node


def path(*keys: str) -> Path:
    """Resolve a key under `paths:` to an absolute path inside the repo."""
    rel = get("paths", *keys)
    if rel is None:
        raise ConfigError(f"paths.{'.'.join(keys)} is not set in config.yaml")
    p = Path(rel)
    return p if p.is_absolute() else (ROOT / p)


# ---------------------------------------------------------------- dot access


@dataclass(frozen=True)
class ConfidenceConfig:
    threshold: float
    w_retrieval: float
    w_llm_self: float
    abstain_on_either: bool
    hard_case_overlap: float
    # When the fabrication guard strips an unsupported claim it also caps the
    # model's self-confidence, because a report that had to be corrected is not
    # evidence we can trust at face value. The cap sits below the abstention
    # threshold on purpose: a caught fabrication forces a decline rather than a
    # slightly-less-confident answer. It is config, not a literal in the
    # pipeline, so the number that decides abstention is reviewable.
    fabrication_cap: float = 0.35

    @classmethod
    def load(cls) -> "ConfidenceConfig":
        return cls(
            threshold=float(get("confidence", "abstention_threshold", default=0.4)),
            w_retrieval=float(get("confidence", "weights", "retrieval", default=0.6)),
            w_llm_self=float(get("confidence", "weights", "llm_self", default=0.4)),
            abstain_on_either=bool(
                get("confidence", "abstain_on_either_component", default=True)
            ),
            hard_case_overlap=float(
                get("confidence", "hard_case_overlap_threshold", default=0.5)
            ),
            fabrication_cap=float(get("confidence", "fabrication_cap", default=0.35)),
        )


@dataclass(frozen=True)
class LLMConfig:
    base_url: str
    model: str
    temperature: float
    max_tokens: int
    timeout_s: int
    max_retries: int
    price_in: float
    price_out: float

    @classmethod
    def load(cls) -> "LLMConfig":
        return cls(
            base_url=os.getenv(
                "OPENROUTER_BASE_URL",
                get("llm", "base_url", default="https://openrouter.ai/api/v1"),
            ),
            model=os.getenv("RJD_MODEL", get("llm", "model", default="openai/gpt-4o-mini")),
            temperature=float(get("llm", "temperature", default=0.1)),
            max_tokens=int(get("llm", "max_tokens", default=1200)),
            timeout_s=int(get("llm", "timeout_s", default=60)),
            max_retries=int(get("llm", "max_retries", default=2)),
            price_in=float(get("llm", "pricing_usd_per_1m_tokens", "input", default=0.15)),
            price_out=float(get("llm", "pricing_usd_per_1m_tokens", "output", default=0.60)),
        )


def api_key_from_env() -> str | None:
    """Never persisted. Empty string and whitespace are treated as absent."""
    for name in ("OPENROUTER_API_KEY", "RJD_API_KEY"):
        value = os.getenv(name)
        if value and value.strip():
            return value.strip()
    return None


def offline_forced() -> bool:
    return os.getenv("RJD_OFFLINE", "0").strip() in {"1", "true", "yes", "on"}


def evaluate_config() -> dict[str, Any]:
    """The evaluation block, with the feedback-driven defaults applied."""
    return {
        "n_cases": int(get("evaluation", "n_cases", default=20)),
        "supported_n_cases": list(get("evaluation", "supported_n_cases", default=[20, 40])),
        "families": list(get("evaluation", "job_families", default=[])),
        "pass_bar_fraction": float(get("evaluation", "pass_bar_fraction", default=0.80)),
        "abstention_rate_ceiling": float(
            get("evaluation", "abstention_rate_ceiling", default=0.30)
        ),
        "conditions": list(get("evaluation", "conditions", default=["A", "B", "C"])),
        "prefill_fields": list(
            get(
                "evaluation",
                "prefill_exact_match_fields",
                default=["full_name", "email", "education_school", "top_skills"],
            )
        ),
    }


def timing_config() -> dict[str, Any]:
    return {
        "enabled": bool(get("timing", "enabled", default=False)),
        "min_timers": int(get("timing", "min_independent_timers", default=3)),
        "target_reduction": float(get("timing", "target_reduction", default=0.30)),
        "timers_file": get("timing", "timers_file", default="data/timing/timers.csv"),
    }


def banner() -> str:
    return str(get("app", "prototype_banner", default="Prototype - not for live sites."))


def non_use_notice() -> str:
    return str(get("app", "non_use_notice", default=""))


def ensure_artifact_dirs() -> Path:
    """Create the artifacts dir (and retrieval store parent) if missing."""
    art = path("artifacts")
    art.mkdir(parents=True, exist_ok=True)
    Path(get("retrieval", "persist_dir", default="artifacts/chroma_db"))
    (ROOT / get("retrieval", "persist_dir", default="artifacts/chroma_db")).parent.mkdir(
        parents=True, exist_ok=True
    )
    return art
