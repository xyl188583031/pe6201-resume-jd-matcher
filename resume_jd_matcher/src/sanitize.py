"""Input hygiene for untrusted text.

The pasted job description is untrusted text (OWASP Top 10 for LLM
Applications, LLM01 Prompt Injection). Two defences, both cheap:

1. `neutralise_injection` strips the obvious instruction-hijack patterns.
2. Every untrusted block is wrapped in explicit delimiters so the model can
   tell instructions from data. The system prompt states that anything inside
   the delimiters is *data*, never an instruction.

This is mitigation, not a guarantee. Nothing here auto-submits anything and
nothing persists, which is what actually bounds the blast radius.
"""

from __future__ import annotations

import hashlib
import re

# Patterns that only ever appear when someone is trying to talk to the model
# through the data channel. Deleting them is safe: no real JD contains
# "ignore all previous instructions".
_INJECTION_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"ignore\s+(all\s+)?(the\s+)?(previous|prior|above)\s+instructions?", re.I),
    re.compile(r"disregard\s+(all\s+)?(the\s+)?(previous|prior|above)\s+.*?(instructions?|rules?)", re.I),
    re.compile(r"forget\s+(everything|all)\s+(you|previously)", re.I),
    re.compile(r"you\s+are\s+now\s+(a|an)\s+\w+", re.I),
    re.compile(r"new\s+(system\s+)?instructions?\s*:", re.I),
    re.compile(r"system\s*(prompt|message)\s*:", re.I),
    # A bare "system:" or "assistant:" role marker. "<|im_start|>system: ..."
    # used to survive as "system: ..." because only the token itself was
    # redacted. No real job description contains a line like this.
    re.compile(r"(?<![A-Za-z])(system|assistant|developer)\s*:", re.I),
    re.compile(r"<\|?(im_start|im_end|system|endoftext)\|?>", re.I),
    re.compile(r"\[\s*(system|assistant|inst)\s*\]", re.I),
    re.compile(r"###\s*(system|instruction)", re.I),
    re.compile(r"jailbreak", re.I),
    re.compile(r"pretend\s+(to\s+be|you\s+are)", re.I),
)

# Zero-width and bidi characters are a classic way to smuggle instructions
# past a naive filter.
_INVISIBLE = re.compile(r"[\u200b-\u200f\u202a-\u202e\u2060-\u2064\ufeff]")

REDACTION = "[removed-untrusted-instruction]"

DELIM_OPEN = "<<<UNTRUSTED_DATA_START>>>"
DELIM_CLOSE = "<<<UNTRUSTED_DATA_END>>>"


def strip_invisible(text: str) -> str:
    return _INVISIBLE.sub("", text)


def neutralise_injection(text: str) -> tuple[str, int]:
    """Return (cleaned_text, n_patterns_hit).

    The hit count is logged so a spike in redactions is visible rather than
    silent - a silent filter is the failure mode we are trying to avoid.
    """
    cleaned = strip_invisible(text)
    hits = 0
    for pattern in _INJECTION_PATTERNS:
        cleaned, n = pattern.subn(REDACTION, cleaned)
        hits += n
    return cleaned, hits


def wrap_untrusted(text: str, label: str = "JOB_DESCRIPTION") -> str:
    """Fence a block so the prompt can say 'this is data, not orders'."""
    return (
        f"{DELIM_OPEN} ({label})\n"
        f"{text}\n"
        f"{DELIM_CLOSE}"
    )


def collapse_whitespace(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def cap_length(text: str, max_chars: int) -> tuple[str, bool]:
    """Truncate defensively. Returns (text, was_truncated)."""
    if max_chars <= 0 or len(text) <= max_chars:
        return text, False
    return text[:max_chars], True


def prepare_untrusted(text: str, max_chars: int) -> tuple[str, dict[str, object]]:
    """Full pipeline for anything that came from outside the process."""
    original_len = len(text)
    cleaned, hits = neutralise_injection(text)
    cleaned = collapse_whitespace(cleaned)
    cleaned, truncated = cap_length(cleaned, max_chars)
    report = {
        "input_chars": original_len,
        "sent_chars": len(cleaned),
        "injection_hits": hits,
        "truncated": truncated,
        # Hash, not content: the log must not become a store of user text.
        "sha256_8": hashlib.sha256(cleaned.encode("utf-8")).hexdigest()[:8],
    }
    return cleaned, report
