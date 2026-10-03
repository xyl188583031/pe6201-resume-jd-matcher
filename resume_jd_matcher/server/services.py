"""Orchestration for the browser assistant. Composes `src/`; owns no policy.

The rule this file is written to obey: **there is exactly one implementation of
every decision.** Nothing here re-implements the abstention rule, the
fabrication guards, the similarity calibration, the prompt-hijack sanitiser or
the retrieval scoring - it calls the same functions the evaluated pipeline
calls, so the browser path and the A/B/C path cannot drift apart.

Where each decision lives
-------------------------
    abstention arithmetic        src/pipeline/confidence.assess          (unchanged)
    per-field withholding        src/pipeline/confidence.field_level_abstentions
    literal-value fabrication    src/llm/extractor.FabricationGuard      (word-bounded)
    skill-claim fabrication      src/taxonomy.has_lexical_support        (word-bounded)
    similarity rescaling         src/retrieval/store.KnowledgeBase.retrieve
    untrusted-JD hygiene         src/sanitize.prepare_untrusted / wrap_untrusted
    retrieval query shape        src/pipeline/runner.build_retrieval_query
    condition A's answer         a deterministic copy, no model
    offline behaviour            src/llm/offline.run_stub

Two decisions belong to this layer, and both are stated in full below rather
than left implicit, because a reader has to be able to disagree with them:

1. **Which confidence components a field gets** (`_evidence_for_field`). The
   task fixes the formula and the threshold; it does not say what the
   "retrieval" slot should carry for a field the JD has nothing to do with. The
   scoping rule is: a field whose answer must be *tailored* to the posting
   (narrative, skills, and the narrative halves of experience and project) gets
   the posting's retrieval score; a field that is a plain fact (personal,
   education, and the fact-shaped halves of experience and project -
   `experience_fact` / `project_fact`) gets the deterministic extraction
   confidence instead, which is the same role that slot plays for condition A.
   Without this, an unrelated posting would abstain on the candidate's email
   address, which is not a confidence judgement anybody could defend.

   The two halves of `experience` and `project` are split for exactly that
   reason. `TAILORED_CATEGORIES` is what chooses between the two rules, and
   `experience` alone named both an employer - a literal the profile holds - and
   a summary, which has to be argued from the posting. Round 3, report.md
   section 5 row 4 (finding 7a).

2. **How prose is checked for fabrication** (`NarrativeGuard`). The existing
   `FabricationGuard` asks "does this literal value appear in the source?", which
   is the right question for a name or a school and the wrong one for a
   paragraph: no honest cover letter is composed only of words that appear in a
   profile, so applying it to prose would withhold every draft. Prose is checked
   for *claims* instead - numbers, multi-word proper names, and skill names -
   and all three still use word-boundary matching.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
from dataclasses import dataclass, field as dc_field
from pathlib import Path
from typing import Any, Iterable, Sequence

from src import config
from src.config import ConfidenceConfig
from src.llm import prompts
from src.llm.client import LLMError, OpenRouterClient
from src.llm.extractor import FabricationGuard
from src.llm.offline import run_stub
from src.pipeline import confidence as conf
from src.pipeline.runner import build_retrieval_query
from src.retrieval.store import KnowledgeBase, build_knowledge_base
from src.rules.fields import extract_fields
from src.sanitize import prepare_untrusted, wrap_untrusted
from src.taxonomy import has_lexical_support, match_skills, ordered_skills

from server import field_map
from server.field_map import Fact, RenderedProfile
from server.schemas import (
    MODULE_NAMES,
    ExtractResumeResponse,
    FieldSuggestion,
    GenerateCounts,
    GenerateRequest,
    GenerateResponse,
    JDAnalysis,
    NormalizedField,
    PrivacyEcho,
    ScanCounts,
    ScanRequest,
    ScanResponse,
)

#: Prefix for a browser-assistant action id. Deliberately different from the
#: evaluation's `run-` prefix so a log line can never be mistaken for an
#: evaluation run.
RUN_PREFIX = "act"

#: Categories whose answer has to be tailored to the posting, and which
#: therefore carry the retrieval score as their evidence component. See the
#: module docstring, decision 1.
TAILORED_CATEGORIES = frozenset({"narrative", "skills", "experience", "project"})

#: Categories whose answer is a literal the authorised profile either holds or
#: does not. The posting is never the evidence for one of these, so "no fact" has
#: to mean "no evidence" rather than "the posting scored zero" - which is what
#: `_evidence_for_field` used to report, and what made a control whose fact the
#: profile simply lacks arrive at the user with "retrieval similarity 0.00 <
#: threshold 0.40". Round 3, report.md section 5 row 5 (finding 7b).
#:
#: `experience_fact` / `project_fact` are in this set because they are facts, the
#: same way `personal` and `education` are. Round 3, report.md section 5 row 4 (finding 7a).
FACT_CATEGORIES = frozenset({"personal", "education", "experience_fact", "project_fact"})

#: User-facing strings for the two hard rules. Kept here so the tests assert on
#: one spelling, and the extension shows exactly what the server decided.
MSG_SENSITIVE = "Extremely sensitive field - fill this in yourself. Nothing was generated, guessed or sent."
MSG_ALREADY_FILLED = (
    "You already entered something in this field. The assistant will not overwrite it; "
    "click regenerate here if you want a new suggestion."
)
MSG_NO_MODEL = (
    "No information for this field in your authorised profile, and condition A uses no model, "
    "so nothing could be drafted. Fill it in yourself, or authorise the module that holds it."
)
MSG_UNSUPPORTED = (
    "The draft was withheld because it contained something your authorised profile does not state."
)
MSG_NO_FACT = (
    "no fact in the authorised profile answers this field; nothing was drafted and "
    "nothing can be offered"
)


# --------------------------------------------------------------------------- #
# Small deterministic helpers
# --------------------------------------------------------------------------- #


def _now_run_id() -> str:
    return f"{RUN_PREFIX}-{time.strftime('%Y%m%d-%H%M%S')}"


def now_run_id() -> str:
    """Public alias: the HTTP layer stamps responses with the same id format."""
    return _now_run_id()


def _cfg() -> ConfidenceConfig:
    return ConfidenceConfig.load()


def _join(*parts: str) -> str:
    """Join non-empty message fragments with a single space."""
    return " ".join(part.strip() for part in parts if part and part.strip())


def new_client(*, api_key: str | None = None, force_offline: bool | None = None) -> OpenRouterClient:
    return OpenRouterClient(api_key=api_key, force_offline=force_offline)


def fit_to_length(value: str, max_length: int | None) -> tuple[str | None, bool]:
    """Condense a value to a field's character limit without adding anything.

    Trimming is not rewriting: the result is a shorter prefix of the profile's
    own wording, cut on a word boundary so a word is never half-presented. When
    even that leaves nothing, the field is reported as unanswerable rather than
    filled with a fragment.

    Returns (value_or_None, was_trimmed).
    """
    if value is None:
        return None, False
    if max_length is None or max_length <= 0:
        return value, False
    if len(value) <= max_length:
        return value, False

    head = value[:max_length].rstrip()
    # Is `head` a whole number of words? It is exactly when the value continues
    # with a separator (or `head` is empty). This replaced a check for "does the
    # cut contain a space", which was true for "Python, PyTo" but false for
    # "Zha" - and so let `fit_to_length("Zhang Wei", 3)` return "Zha", a
    # half-presented name, contradicting the rule stated above.
    continues_at_boundary = bool(head) and value[len(head)] in " \t\n,;:-–—/|"
    if continues_at_boundary:
        cut = head
    else:
        # The limit lands inside a word. Drop that word entirely rather than
        # present a fragment of it; if nothing survives, there is no honest
        # shorter answer and the caller reports the field as unanswerable.
        cut = head[: head.rfind(" ")].rstrip() if " " in head else ""

    trimmed = cut.strip(" \t,;:-–—/|")
    if len(trimmed) < 3:
        return None, True
    return trimmed, True


#: Everyday spellings of the same qualification. A select control offers "MSc"
#: while a profile says "Master of Science"; without this the assistant reports
#: the field as unanswerable even though it plainly has the answer. Grouped by
#: equivalence, so the match is between groups and never between two different
#: qualifications.
_OPTION_ALIAS_GROUPS: tuple[frozenset[str], ...] = (
    frozenset(
        {
            "bachelor", "bachelors", "bachelor of science", "bachelor of engineering",
            "bachelor of arts", "bsc", "bs", "b eng", "beng", "b a", "ba", "undergraduate",
        }
    ),
    frozenset(
        {
            "master", "masters", "master of science", "master of engineering",
            "master of arts", "msc", "ms", "m eng", "meng", "m a", "ma", "postgraduate",
        }
    ),
    frozenset({"phd", "ph d", "doctorate", "doctoral", "doctor of philosophy", "dphil"}),
    frozenset({"mba", "master of business administration"}),
)


def _option_group(text: str) -> int | None:
    normalised = re.sub(r"[^a-z0-9 ]+", " ", (text or "").lower())
    normalised = re.sub(r"\s+", " ", normalised).strip()
    if not normalised:
        return None
    for index, group in enumerate(_OPTION_ALIAS_GROUPS):
        for member in group:
            if normalised == member or normalised.startswith(member + " "):
                return index
    return None


def match_option(value: str | None, options: Sequence[str]) -> str | None:
    """Snap a proposed answer onto one of a select/radio/checkbox control's options.

    A value the control does not offer must never be written into it: the browser
    would silently discard it and the user would see an empty field after being
    told it had been filled. Unmatchable -> None -> reported as missing.

    Three passes, cheapest first: exact, punctuation-insensitive, then the
    qualification-alias groups above. All three are equality tests, never fuzzy
    scoring - an approximate match could write the wrong degree onto an
    application, which is worse than leaving it for the user.
    """
    if value is None:
        return None
    if not options:
        return value
    wanted = re.sub(r"\s+", " ", value.strip().lower())
    if not wanted:
        return None
    for option in options:
        if re.sub(r"\s+", " ", option.strip().lower()) == wanted:
            return option
    stripped_wanted = re.sub(r"[^a-z0-9 ]+", "", wanted)
    for option in options:
        if re.sub(r"[^a-z0-9 ]+", "", option.lower()) == stripped_wanted:
            return option
    wanted_group = _option_group(wanted)
    if wanted_group is not None:
        for option in options:
            if _option_group(option) == wanted_group:
                return option
    return None


_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")
_PROPER = re.compile(r"\b[A-Z][A-Za-z0-9&'’\.\-]*(?:\s+[A-Z][A-Za-z0-9&'’\.\-]*)+")

#: Leading words that are capitalised only because they start a sentence.
_SENTENCE_WORDS = frozenset(
    {
        "i", "my", "me", "the", "this", "that", "these", "those", "in", "as", "at", "it",
        "we", "our", "with", "for", "and", "but", "when", "while", "during", "after",
        "before", "by", "to", "from", "if", "so", "because", "their", "there", "his",
        "her", "its", "you", "your", "they", "he", "she", "however", "although",
        "through", "within", "using", "built", "led", "worked", "developed", "also",
        "both", "each", "every", "over", "under", "across", "since", "most", "many",
        "a", "an", "on", "of", "or", "not", "no", "do", "did", "does", "have", "has",
    }
)

#: Words whose trailing full stop belongs to the word, not to the sentence.
#: Stored in bare form, because that is how `_entity_chunks` compares them.
_ABBREV = frozenset(
    {
        "inc", "ltd", "llc", "llp", "plc", "co", "corp", "pte", "pvt", "pty",
        "gmbh", "sdn", "bhd", "ag", "sa", "nv", "bv", "ab", "oy", "as", "kk",
        "jr", "sr", "dr", "prof", "rev", "st", "mt", "vs", "etc", "dept", "div",
        "univ", "inst", "no", "vol", "phd", "bsc", "msc", "beng", "meng", "mba",
    }
)


def _entity_chunks(phrase: str) -> list[str]:
    """Split one `_PROPER` match at sentence boundaries.

    `_PROPER`'s character class accepts `.`, so the sentence "I built dashboards
    at Acme Corp. My team reported weekly." matched as the single phrase
    "Acme Corp. My". No source text contains that string, so an honest sentence
    was reported as an invented employer called "Acme Corp My" and the whole
    draft was withheld - the same failure the trailing-full-stop fix addressed,
    one sentence further along.

    A full stop that ends a word therefore ends the entity, unless the next word
    is also an abbreviated or organisational form - which is what keeps
    "Acme Pte. Ltd." in one piece.
    """
    chunks: list[str] = []
    current: list[str] = []
    tokens = re.findall(r"\S+", phrase)
    for index, token in enumerate(tokens):
        current.append(token)
        if not token.endswith("."):
            continue
        bare = re.sub(r"[^A-Za-z0-9]", "", token).lower()
        following = tokens[index + 1] if index + 1 < len(tokens) else ""
        next_bare = re.sub(r"[^A-Za-z0-9]", "", following).lower()
        if bare in _ABBREV and next_bare in _ABBREV:
            continue  # "Pte." followed by "Ltd." is one name, not two sentences
        chunks.append(" ".join(current))
        current = []
    if current:
        chunks.append(" ".join(current))
    return chunks


class NarrativeGuard:
    """Fabrication check for free prose. Complements `FabricationGuard`.

    Checks claims, not wording: numbers, multi-word proper names, and skill
    names. Anything it flags withholds the whole draft, because quietly deleting
    a sentence would leave prose the model did not write, and the user could not
    tell what had changed.

    Known gap, stated rather than hidden: a *single* capitalised token is not
    checked, because distinguishing "Singapore" from "I" without a gazetteer is
    not something a regex can do. Multi-word names - where invented employers and
    institutions actually appear - are checked, every narrative field is marked
    `needs_user_confirmation`, and the draft is never written into a form until
    the user clicks. See `server/README.md`.
    """

    def __init__(self, source_text: str) -> None:
        self._source = source_text or ""
        self._source_norm = re.sub(r"\s+", " ", self._source.lower())
        self._source_numbers = set(_NUMBER.findall(self._source))
        self._source_skills = match_skills(self._source)

    @staticmethod
    def _tokens_of(phrase: str) -> list[str]:
        return re.findall(r"[A-Za-z0-9&'’\.\-]+", phrase)

    def check(self, text: str) -> list[str]:
        """Return the unsupported claims found in `text` (empty means clean)."""
        if not text or not text.strip():
            return []
        hits: list[str] = []

        # 1. numbers: years, grades, percentages, counts
        for number in _NUMBER.findall(text):
            if number not in self._source_numbers and number not in self._source:
                hits.append(f"number {number!r}")

        # 2. multi-word proper names: employers, institutions, products.
        #    Each match is first cut at sentence boundaries, so a name at the end
        #    of one sentence is not welded to the capitalised word that opens the
        #    next. See `_entity_chunks`.
        for match in _PROPER.findall(text):
            for phrase in _entity_chunks(match):
                tokens = self._tokens_of(phrase)
                # Drop leading sentence-start words so "In my internship at X" is
                # not treated as one entity name.
                while tokens and tokens[0].lower() in _SENTENCE_WORDS:
                    tokens.pop(0)
                # Strip surrounding punctuation from each word. `_PROPER`'s
                # character class includes `.` and `-`, so a name at the end of a
                # sentence was read as "Acme Corp." and then failed to match the
                # source's "Acme Corp" - which withheld a perfectly well-grounded
                # cover letter. The comparison is on words, not on punctuation.
                words = [
                    re.sub(r"^[^A-Za-z0-9&]+|[^A-Za-z0-9]+$", "", token) for token in tokens
                ]
                words = [word for word in words if word]
                if len(words) < 2:
                    continue
                # Any non-alphanumeric run between two words counts as the
                # separator, so "Acme  Corp" and "Acme-Corp" are the same entity
                # as "Acme Corp".
                pattern = (
                    r"(?<![a-z0-9])"
                    + r"[^a-z0-9]+".join(re.escape(word.lower()) for word in words)
                    + r"(?![a-z0-9])"
                )
                if not re.search(pattern, self._source_norm):
                    hits.append(f"name {' '.join(words)!r}")

        # 3. skills, through the shared word-boundary check
        for skill in sorted(match_skills(text) - self._source_skills):
            if not has_lexical_support(skill, self._source, present=self._source_skills):
                hits.append(f"skill {skill!r}")

        # de-duplicate, keep first-seen order
        seen: list[str] = []
        for hit in hits:
            if hit not in seen:
                seen.append(hit)
        return seen


# --------------------------------------------------------------------------- #
# Sanitising and prompt assembly
# --------------------------------------------------------------------------- #


def _max_input_chars() -> int:
    return int(config.get("privacy", "max_input_chars", default=20000))


@dataclass
class PreparedInputs:
    jd_clean: str
    jd_report: dict[str, Any]
    profile_clean: str
    rendered: RenderedProfile
    notes: list[str] = dc_field(default_factory=list)


def prepare_inputs(
    profile: dict[str, Any], authorised_modules: Iterable[str], jd_text: str
) -> PreparedInputs:
    """Render the authorised profile and sanitise both untrusted blocks.

    The order matters and is deliberate: render -> sanitise -> extract facts.
    The sanitised text is what the model sees *and* what the guards check against
    *and* what the deterministic extractor reads, so all three agree. Extracting
    facts from the pre-sanitised text would let a value that sanitising removed
    pass the guard on a technicality.
    """
    rendered_raw = field_map.render_profile(profile, authorised_modules)
    notes: list[str] = []

    if rendered_raw.dropped_modules:
        notes.append(
            "server stripped module(s) that were not authorised: "
            + ", ".join(rendered_raw.dropped_modules)
        )
    if rendered_raw.empty_modules:
        notes.append(
            "authorised module(s) carried no data: " + ", ".join(rendered_raw.empty_modules)
        )

    max_chars = _max_input_chars()
    if bool(config.get("privacy", "sanitize_untrusted_text", default=True)):
        jd_clean, jd_report = prepare_untrusted(jd_text or "", max_chars)
        profile_clean, profile_report = prepare_untrusted(rendered_raw.text, max_chars)
    else:
        jd_clean, jd_report = jd_text or "", {"sanitised": False}
        profile_clean, profile_report = rendered_raw.text, {"sanitised": False}

    if jd_report.get("injection_hits"):
        notes.append(
            f"the posting contained {jd_report['injection_hits']} instruction-hijack "
            "pattern(s); they were redacted before the model saw the text"
        )
    if profile_report.get("injection_hits"):
        notes.append(
            f"the profile contained {profile_report['injection_hits']} instruction-hijack "
            "pattern(s); they were redacted before the model saw the text"
        )

    rendered = RenderedProfile(
        text=profile_clean,
        module_texts={
            module: text for module, text in rendered_raw.module_texts.items()
        },
        used_modules=list(rendered_raw.used_modules),
        dropped_modules=list(rendered_raw.dropped_modules),
        empty_modules=list(rendered_raw.empty_modules),
    )
    return PreparedInputs(
        jd_clean=jd_clean,
        jd_report=jd_report,
        profile_clean=profile_clean,
        rendered=rendered,
        notes=notes,
    )


def field_list_block(fields: Sequence[NormalizedField]) -> str:
    """The numbered field list the model answers against.

    Sensitive fields are absent, and no field's current value is included. Both
    omissions are deliberate: a document number must not reach a third party, and
    a value the user typed must not be echoed into a prompt where it could come
    back as a "model suggestion" the user then mistakes for the model's own work.
    The server enforces non-overwrite itself (`overwrite_filled`), so the model
    does not need to see the current value in order to respect it.
    """
    lines: list[str] = []
    for item in fields:
        if item.sensitive or not item.fillable:
            continue
        bits = [
            f"id={item.field_id}",
            f"label={item.label or '(no label)'}",
            f"type={item.type}",
            f"required={'yes' if item.required else 'no'}",
        ]
        if item.max_length:
            bits.append(f"max_length={item.max_length}")
        if item.options:
            bits.append("options=" + " | ".join(item.options[:20]))
        if item.help_text:
            bits.append("help=" + re.sub(r"\s+", " ", item.help_text)[:160])
        lines.append("- " + "; ".join(bits))
    return "\n".join(lines) or "(no fillable fields)"


# --------------------------------------------------------------------------- #
# Retrieval
# --------------------------------------------------------------------------- #


class KnowledgeBaseProvider:
    """Builds the retrieval index once and shares it.

    The embedder costs seconds to load and the index lock allows one writer, so
    a per-request build would both be slow and start refusing under concurrent
    requests. Built into the server's own directory so it can never collide with
    an evaluation run's `--out-dir`.
    """

    def __init__(self, persist_dir: Path | None = None) -> None:
        self._persist_dir = Path(persist_dir) if persist_dir else (
            config.ROOT / "artifacts" / "server_index" / "chroma_db"
        )
        self._kb: KnowledgeBase | None = None
        self._error: str | None = None
        self._lock = threading.Lock()

    def get(self) -> KnowledgeBase | None:
        with self._lock:
            if self._kb is not None:
                return self._kb
            if self._error is not None:
                return None
            try:
                self._kb = build_knowledge_base(persist_dir=self._persist_dir)
            except Exception as exc:  # noqa: BLE001 - retrieval is optional, never fatal
                self._error = f"{type(exc).__name__}: {exc}"
                return None
            return self._kb

    @property
    def error(self) -> str | None:
        return self._error

    def describe(self) -> dict[str, Any]:
        kb = self._kb
        if kb is None:
            return {
                "available": False,
                "error": self._error or "not built yet",
                "persist_dir": str(self._persist_dir),
            }
        info = kb.describe()
        info["available"] = True
        info["persist_dir"] = str(self._persist_dir)
        return info

    def close(self) -> None:
        with self._lock:
            if self._kb is not None:
                try:
                    self._kb.close()
                except BaseException:  # noqa: BLE001
                    pass
                self._kb = None


#: Process-wide provider used by the HTTP layer. Tests construct their own.
DEFAULT_KB_PROVIDER = KnowledgeBaseProvider()


@dataclass
class RetrievalContext:
    """One retrieval, shared by every field that needs it."""

    score: float | None = None
    chunk_ids: list[str] = dc_field(default_factory=list)
    notes: list[str] = dc_field(default_factory=list)

    @property
    def present(self) -> bool:
        return self.score is not None


def retrieve_for_jd(
    jd_clean: str,
    *,
    kb: KnowledgeBase | None,
    enabled: bool = True,
) -> RetrievalContext:
    """Calibrated top-1 retrieval score for the posting, via `src/` scoring."""
    if not enabled or kb is None or not jd_clean.strip():
        return RetrievalContext()
    try:
        jd_skills = ordered_skills(match_skills(jd_clean))
        query = build_retrieval_query(jd_clean, jd_skills)
        result = kb.retrieve(query)
    except Exception as exc:  # noqa: BLE001 - a retrieval failure must not fail the request
        return RetrievalContext(notes=[f"retrieval unavailable: {type(exc).__name__}: {exc}"])
    notes: list[str] = []
    if not result.hits:
        notes.append("retrieval returned no chunks")
    return RetrievalContext(
        score=float(result.top_score),
        chunk_ids=result.chunk_ids,
        notes=notes,
    )


def _evidence_for_field(
    field: NormalizedField,
    *,
    condition: str,
    retrieval: RetrievalContext,
    fact: Fact | None,
) -> float | None:
    """Which number fills the formula's `retrieval` slot for this field.

    See the module docstring, decision 1. In one line: tailored answers are
    grounded by the posting, plain facts about the person are grounded by the
    source text's own evidence score.

    The tailored branch returns None when there is no retrieval, and that is
    deliberate. It used to fall back to `fact.confidence`, which made the two
    conditions disagree with the evaluation and - worse - mislabelled the number:
    under condition B a skills field reported `components_present == ["retrieval"]`
    when no retrieval had happened at all. Condition B is defined as model-only,
    so the honest answer for a tailored field with no retrieved notes is "we have
    no grounding for this", which `assess` turns into the model's own confidence
    and nothing else. A field that is a plain fact about the person is unaffected
    - it still gets its extraction confidence, in every condition, because the
    posting was never the relevant evidence for it.
    """
    if condition.upper() == "A":
        # No model exists, so this slot is the only component. Carrying the
        # deterministic extraction confidence here is exactly what
        # `run_case`/condition A does with `baseline.evidence_confidence`.
        return fact.confidence if fact else None
    if field.category in TAILORED_CATEGORIES:
        # Model-only conditions (B, and C when the index is unavailable) have no
        # retrieved notes, so there is no retrieval evidence to report.
        return retrieval.score if retrieval.present else None
    # A plain fact about the person: the posting has no bearing on the answer.
    if fact:
        return fact.confidence
    if field.category in FACT_CATEGORIES:
        # ... and with no fact there is no evidence at all. Handing the retrieval
        # score to this slot was how a field whose fact the profile does not hold
        # ended up reporting "retrieval similarity 0.00 < threshold 0.40": the
        # arithmetic was real, but it named the posting as the cause when the
        # cause was the profile. Condition A already returned None here, so this
        # also removes a disagreement between the conditions. Round 3, report.md
        # section 5 row 5 (finding 7b).
        return None
    # `unknown`: we cannot say what this control is, so the posting is the only
    # weak signal there is.
    return retrieval.score if retrieval.present else None


# --------------------------------------------------------------------------- #
# /scan
# --------------------------------------------------------------------------- #


def scan(request: ScanRequest) -> ScanResponse:
    """Normalise a page's controls. Pure function of the request."""
    fields = field_map.normalise_fields(request.fields)
    counts = ScanCounts(
        total=len(fields),
        fillable=sum(1 for f in fields if f.fillable),
        required=sum(1 for f in fields if f.required and f.fillable),
        already_filled=sum(1 for f in fields if f.already_filled),
        sensitive=sum(1 for f in fields if f.sensitive),
        skipped=sum(1 for f in fields if not f.fillable),
    )
    notes: list[str] = []
    if counts.sensitive:
        notes.append(
            f"{counts.sensitive} field(s) look like identity documents; they are never "
            "generated, never transmitted and never filled"
        )
    if counts.skipped:
        notes.append(
            f"{counts.skipped} control(s) are not fillable (hidden, buttons, file pickers, "
            "password fields, or an unsupported element)"
        )
    return ScanResponse(
        url=request.url,
        page_title=request.page_title,
        counts=counts,
        fields=fields,
        notes=notes,
    )


# --------------------------------------------------------------------------- #
# /extract_resume
# --------------------------------------------------------------------------- #

#: Where a resume's facts are looked for, as (profile path, extractor key).
#: Ordered the way a person writes their own details, so `extracted_fields`
#: reads as a list rather than a dump.
RESUME_FIELD_MAP: tuple[tuple[str, str], ...] = (
    ("personal_info.full_name", "full_name"),
    ("personal_info.email", "email"),
    ("personal_info.phone", "phone"),
    ("education[0].school", "education_school"),
    ("education[0].degree", "education_degree"),
    ("education[0].major", "education_major"),
    ("education[0].end", "graduation_year"),
)

#: Confidence below which an extracted value is worth the user's eyes.
#: Deliberately the same 0.7 `_decide_field` uses to decide whether a plain fact
#: may skip confirmation, so "needs a look" means one thing in this module
#: rather than two. `src/rules/fields.py` publishes the per-field numbers and
#: says outright that they are mechanism-based rather than calibrated:
#: `graduation_year` (0.55) is the lowest because it is the only one that
#: guesses, taking the largest year in the document.
RESUME_CONFIRM_LINE = 0.7


def extract_profile_from_text(text: str) -> ExtractResumeResponse:
    """Turn resume text into a profile the user can review and correct.

    Reuses the two pieces the rest of the server already uses, rather than
    growing a resume parser of its own:

    * `src.rules.fields.extract_fields` - the literal extractor that condition A
      and the offline stub share, so a resume read here and a resume read by
      condition A cannot disagree about what an email address looks like;
    * `field_map.render_profile` - the renderer `/generate` uses, so the note
      below reports what the profile would actually become on the wire.

    The text is sanitised before extraction, in the same order `prepare_inputs`
    documents (sanitise, then extract): a value that sanitising removed must not
    survive by being read out of the pre-sanitised copy.

    Nothing is persisted. The text arrives in the request, the profile goes back
    in the response, and neither is written anywhere - the H3 constraint the rest
    of the assistant already holds to.
    """
    if not (text or "").strip():
        raise ValueError("no resume text was supplied")

    cleaned, report = prepare_untrusted(text, _max_input_chars())
    extracted = extract_fields(cleaned)
    values: dict[str, Any] = dict(extracted.get("fields") or {})
    confidence: dict[str, Any] = dict(extracted.get("field_confidence") or {})

    profile: dict[str, Any] = {
        "personal_info": {},
        "education": [],
        "internship": [],
        "projects": [],
    }
    education: dict[str, Any] = {}
    filled: list[str] = []
    uncertain: list[str] = []

    for path, key in RESUME_FIELD_MAP:
        raw = values.get(key)
        value = "" if raw is None else str(raw).strip()
        if not value:
            # Nothing was read for this key. That is exactly what the user has to
            # know: it is not "the resume does not say", it is "no rule found it".
            uncertain.append(path)
            continue
        education_or_personal, _, leaf = path.partition(".")
        if education_or_personal == "personal_info":
            profile["personal_info"][leaf] = value
        else:
            education[leaf] = value
        filled.append(path)
        if float(confidence.get(key) or 0.0) < RESUME_CONFIRM_LINE:
            uncertain.append(path)

    if education:
        profile["education"] = [education]

    notes: list[str] = [
        "the literal extractor reads personal details and education only. Work "
        "history and projects are not attempted, so those two modules come back "
        "empty however much the resume says about them, and are filled in by hand."
    ]
    if report.get("injection_hits"):
        notes.append(
            f"the resume text contained {report['injection_hits']} instruction-hijack "
            "pattern(s); they were redacted before extraction"
        )
    if report.get("truncated"):
        notes.append(
            f"the resume text was truncated to {report.get('sent_chars')} characters "
            f"before extraction (it arrived as {report.get('input_chars')})"
        )

    rendered = field_map.render_profile(profile, MODULE_NAMES)
    notes.append(
        f"the extracted profile renders to {len(rendered.text)} characters across "
        f"module(s): {', '.join(rendered.used_modules) or 'none'}"
    )

    return ExtractResumeResponse(
        profile=profile,
        extracted_fields=filled,
        uncertain_fields=uncertain,
        source="resume_text",
        notes=notes,
    )


# --------------------------------------------------------------------------- #
# JD analysis (shared by /jd/analyze and /generate)
# --------------------------------------------------------------------------- #


def analyse_jd(
    jd_clean: str,
    *,
    profile_clean: str,
    client: OpenRouterClient,
    condition: str,
) -> tuple[JDAnalysis, list[str]]:
    """One implementation of the `jd_analysis` block, used by both endpoints.

    `condition` A means "no model at all", and the deterministic responder for
    that is the same rule-based extractor the offline stub uses - so A calls it
    rather than growing a second copy of literal JD parsing.
    """
    notes: list[str] = []
    if not jd_clean.strip():
        return JDAnalysis(), ["no posting supplied; jd_analysis is empty"]

    if str(condition).upper() == "A":
        payload = run_stub(
            "jd_analyze",
            {"jd_text": jd_clean, "profile_text": profile_clean},
        )
        notes.append("condition A: the posting was analysed by literal keyword matching only")
    else:
        fenced = wrap_untrusted(jd_clean, label="JOB_DESCRIPTION")
        candidate_block = (
            wrap_untrusted(profile_clean, label="CANDIDATE_PROFILE") if profile_clean.strip() else None
        )
        result = client.complete_json(
            system=prompts.JD_ANALYZE_SYSTEM,
            user=prompts.jd_analyze_user(fenced, candidate_block),
            task="jd_analyze",
            stub_input={"jd_text": jd_clean, "profile_text": profile_clean},
        )
        payload = result.content or {}

    def _strings(key: str, limit: int = 20) -> list[str]:
        values = payload.get(key) or []
        if not isinstance(values, list):
            return []
        out = [str(v).strip() for v in values if str(v).strip()]
        return out[:limit]

    analysis = JDAnalysis(
        job_title=str(payload.get("job_title") or "").strip()[:200],
        company=str(payload.get("company") or "").strip()[:200],
        location=str(payload.get("location") or "").strip()[:200],
        responsibilities=_strings("responsibilities", 8),
        requirements=_strings("requirements", 24),
        keywords=_strings("keywords", 30),
        bonus_points=_strings("bonus_points", 12),
        missing_from_user_profile=_strings("missing_from_user_profile", 24),
    )
    return analysis, notes


# --------------------------------------------------------------------------- #
# /generate
# --------------------------------------------------------------------------- #


def _model_field_map(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Index the model's field entries by id, tolerating a malformed list."""
    out: dict[str, dict[str, Any]] = {}
    for item in payload.get("fields") or []:
        if not isinstance(item, dict):
            continue
        fid = str(item.get("field_id") or "").strip()
        if fid and fid not in out:
            out[fid] = item
    return out


def _as_confidence(value: Any) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return max(0.0, min(1.0, number))


def _decide_field(
    field: NormalizedField,
    *,
    proposed: str | None,
    model_confidence: float | None,
    model_source: str,
    jd_relevance: str,
    model_message: str,
    fact: Fact | None,
    evidence: float | None,
    guard: FabricationGuard,
    narrative_guard: NarrativeGuard,
    cfg: ConfidenceConfig,
    condition: str,
    overwrite_filled: bool,
) -> tuple[FieldSuggestion, list[str]]:
    """Turn one field's raw inputs into the suggestion the UI renders.

    Returns the suggestion and any risk flags it raises.
    """
    risks: list[str] = []
    suggestion = FieldSuggestion(
        field_id=field.field_id,
        label=field.label or field.name or field.field_id,
        type=field.type,
        required=field.required,
        max_length=field.max_length,
        tag=field.tag,
        selector=field.selector,
        current_value=field.current_value,
        already_filled=field.already_filled,
        options=list(field.options),
        source=model_source or (fact.source if fact else ""),
        jd_relevance=jd_relevance,
        message=model_message,
    )

    assessment = conf.assess(
        retrieval_similarity=evidence,
        llm_self_confidence=model_confidence,
        cfg=cfg,
    )
    # Rounded at the assignment, not only in the model validator: pydantic does
    # not re-validate on attribute assignment, so the constructor's rounding was
    # being bypassed and the response carried 0.8500000000000001.
    suggestion.confidence = round(float(assessment.combined), 4)
    suggestion.components_present = list(assessment.components_present)
    suggestion.reasons = list(assessment.reasons)
    # `abstained` means one thing: the abstention rule withheld a candidate value.
    # It is set below, in the one branch where that happens. Seeding it from the
    # raw assessment counted a field with nothing to offer at all - and a field
    # the user had already filled - as "withheld for weak evidence", which
    # double-counted them against `missing` and mislabelled the reason in the
    # panel's summary. `reasons` still carries the assessment either way, so the
    # information is not lost, only the count is made truthful.
    suggestion.abstained = False

    # ---- hard rule 1: extremely sensitive --------------------------------
    if field.sensitive:
        suggestion.sensitive_skipped = True
        suggestion.suggested_value = None
        # Blank the echoed current value too. The page's own value for a passport
        # field is a document number; echoing it back would put it in the panel's
        # state and - because the panel persists its drafts - into browser
        # storage. It never reaches the model either way (sensitive fields are
        # excluded from the prompt), but it must not be copied around.
        suggestion.current_value = ""
        suggestion.confidence = 0.0
        suggestion.components_present = []
        suggestion.reasons = [field.sensitive_reason]
        suggestion.needs_user_confirmation = True
        suggestion.message = MSG_SENSITIVE
        # Skipped is not the same as declined-for-low-confidence, and the counts
        # distinguish them. Leaving `abstained` set here made every passport field
        # appear in the "withheld for weak evidence" total.
        suggestion.abstained = False
        return suggestion, risks

    # ---- hard rule 2: never overwrite what the user typed -----------------
    if field.already_filled and not overwrite_filled:
        suggestion.suggested_value = None
        suggestion.needs_user_confirmation = True
        suggestion.message = MSG_ALREADY_FILLED
        return suggestion, risks

    # ---- choose the value, and check that it is allowed -------------------
    value: str | None = None
    trimmed = False
    used_fact_fallback = False
    unsupported_draft = False

    def option_problem(raw_value: str) -> str:
        """Why `raw_value` cannot go into this control, or "" when it can.

        Both value sources go through here - the model's draft AND the profile's
        own literal. Applying it to only one of them was a real bug: the model
        drafted "Master of Science", a control offering BSc/MSc/PhD rejected it,
        the code fell back to the profile's "Master of Science", and the field
        was reported as filled with a value the browser would silently discard.
        """
        if not field.options:
            return ""
        if match_option(raw_value, field.options) is not None:
            return ""
        return f"it is not one of this control's options ({', '.join(field.options[:6])})"

    def localise(raw_value: str) -> str:
        """Snap onto an option when the control offers a fixed list."""
        if not field.options:
            return raw_value
        return match_option(raw_value, field.options) or raw_value

    def reject_option_mismatch(raw_value: str, problem: str) -> tuple[FieldSuggestion, list[str]]:
        suggestion.suggested_value = None
        suggestion.missing = True
        suggestion.needs_user_confirmation = True
        suggestion.message = f"nothing was written: {raw_value!r} {problem}"
        risks.append(
            f"{suggestion.label or field.field_id}: no option matches the candidate's data"
        )
        return suggestion, risks

    if proposed and proposed.strip():
        candidate = proposed.strip()

        problem = option_problem(candidate)
        if problem:
            return reject_option_mismatch(candidate, problem)
        # Option snapping happens AFTER the guard, not before. Snapping first
        # turned "Master of Science" into "MSc" and then failed the guard on
        # "MSc", which is not in the profile - so the field was reported as an
        # unsupported model draft when the draft had been supported all along.

        if field.category == "narrative":
            hits = narrative_guard.check(candidate)
            if hits:
                suggestion.suggested_value = None
                # `missing` here means the same thing it means everywhere else:
                # no value is on offer for this field. This branch used to leave
                # it False, which put the field in no count at all and made the
                # response's totals fail to add up. Why there is no value is
                # carried in `message` and `risk_flags`, which is where it
                # belongs; the flag is about the state, not the reason.
                suggestion.missing = True
                suggestion.needs_user_confirmation = True
                suggestion.message = MSG_UNSUPPORTED + " Unsupported: " + "; ".join(hits[:3])
                risks.append(
                    f"{suggestion.label or field.field_id}: a draft was withheld for "
                    f"unsupported claim(s): {'; '.join(hits[:3])}"
                )
                return suggestion, risks
            # Prose can never be a literal, so the strict value guard does not
            # apply; the claim guard above is what protects it.
            value = localise(candidate)
            suggestion.source = model_source or suggestion.source
        elif guard.supports(candidate):
            value = localise(candidate)
        elif fact is not None:
            # The model's wording is unsupported but the profile holds a literal
            # for this field. Use the literal rather than dropping the field: it
            # is grounded by construction.
            fallback_problem = option_problem(fact.value)
            if fallback_problem:
                return reject_option_mismatch(fact.value, fallback_problem)
            value = localise(fact.value)
            used_fact_fallback = True
            unsupported_draft = True
            suggestion.source = fact.source
            risks.append(
                f"{suggestion.label or field.field_id}: the model's draft was not supported by "
                "the authorised profile, so the profile's own value was used instead"
            )
        else:
            suggestion.suggested_value = None
            suggestion.missing = True
            suggestion.needs_user_confirmation = True
            suggestion.message = MSG_UNSUPPORTED
            risks.append(
                f"{suggestion.label or field.field_id}: the draft was not supported by the "
                "authorised profile and nothing else could fill it"
            )
            return suggestion, risks
    elif fact is not None:
        # The model returned nothing for this field, so the profile's own literal
        # is the answer - still subject to the control's option list.
        problem = option_problem(fact.value)
        if problem:
            return reject_option_mismatch(fact.value, problem)
        value = localise(fact.value)
        used_fact_fallback = True
        suggestion.source = fact.source

    if value is None:
        suggestion.suggested_value = None
        suggestion.missing = True
        suggestion.needs_user_confirmation = True
        if fact is None and field.category in FACT_CATEGORIES:
            # The field is a plain fact, the profile holds no such fact, and no
            # draft arrived. Only this branch knows all three at once, so it is
            # the only place that can name the cause a user can act on - the
            # profile - rather than leaving the confidence arithmetic's wording
            # ("retrieval similarity 0.00 < threshold 0.40") to point at the
            # posting. The numbers themselves are unchanged and still reported in
            # `confidence` / `components_present`. Round 3, report.md section
            # 5 row 5 (finding 7b).
            suggestion.reasons = [MSG_NO_FACT]
        if condition.upper() == "A":
            suggestion.message = suggestion.message or MSG_NO_MODEL
        else:
            suggestion.message = suggestion.message or (
                "nothing in your authorised profile answers this field; fill it in yourself, "
                "or authorise the module that holds the answer"
            )
        return suggestion, risks

    # ---- the abstention rule decides whether we may offer it --------------
    if assessment.abstain:
        suggestion.abstained = True
        suggestion.suggested_value = None
        suggestion.needs_user_confirmation = True
        reason = assessment.reasons[0] if assessment.reasons else "confidence below threshold"
        advice = (
            "Paste more of the posting, or add more of your profile, and generate again."
            if "retrieval" in reason
            else "Fill this one in yourself, or authorise the part of your profile that covers it."
        )
        suggestion.message = f"withheld rather than guessed: {reason}. {advice}"
        return suggestion, risks

    # ---- fits the field's limit ------------------------------------------
    fitted, trimmed = fit_to_length(value, field.max_length)
    if fitted is None:
        suggestion.suggested_value = None
        suggestion.missing = True
        suggestion.needs_user_confirmation = True
        suggestion.message = (
            f"the answer cannot be expressed in {field.max_length} characters without dropping "
            "a fact it needs"
        )
        risks.append(
            f"{suggestion.label or field.field_id}: unanswerable inside the {field.max_length}-character limit"
        )
        return suggestion, risks

    suggestion.suggested_value = fitted
    # Both notes are appended rather than chosen between. They used to be an
    # if/elif chain, so a value that was BOTH substituted from the profile and
    # then trimmed reported only the shortening - and the user was never told
    # that the model's wording had been thrown away.
    if unsupported_draft:
        suggestion.message = _join(
            suggestion.message,
            "The model's draft was not supported by your authorised profile, so your profile's "
            "own wording was used instead. Check it before sending.",
        )
    if trimmed:
        suggestion.message = _join(
            suggestion.message,
            f"Shortened to fit the {field.max_length}-character limit; check the cut.",
        )
    if not suggestion.message and used_fact_fallback:
        suggestion.message = "Taken from your profile directly."

    # Every value is a suggestion (task invariant 10). Only a high-confidence
    # plain fact skips the confirmation flag, and the UI still requires a click.
    #
    # `experience_fact` / `project_fact` are deliberately NOT added to this set,
    # even though they are facts. They were outside it before the split (their
    # category was `experience` / `project`), and widening the exemption at the
    # same time would drop a confirmation gate on the strength of a taxonomy
    # change nobody asked for. Category membership decides which evidence judges
    # a field; it does not decide how much trust to extend to it.
    suggestion.needs_user_confirmation = not (
        not trimmed
        and field.category in {"personal", "education"}
        and suggestion.confidence >= 0.7
    )
    return suggestion, risks


def generate(
    request: GenerateRequest,
    *,
    client: OpenRouterClient | None = None,
    kb_provider: KnowledgeBaseProvider | None = None,
    run_id: str | None = None,
) -> GenerateResponse:
    """Draft suggestions for a page's fields.

    One model call for the field drafts, plus one for the posting analysis when a
    posting was supplied. Conditions are the same three as the evaluation: A is
    rules only, B is the model alone, C adds retrieved notes.
    """
    client = client or new_client()
    condition = request.condition.upper()
    run_id = run_id or _now_run_id()
    cfg = _cfg()

    prepared = prepare_inputs(request.profile, request.authorised_modules, request.jd_text)
    notes = list(prepared.notes)
    fields = field_map.normalise_fields(request.fields)
    considered = [f for f in fields if f.fillable]
    fillable = [f for f in considered if not f.sensitive]

    # ---- retrieval (condition C only) ------------------------------------
    retrieval = RetrievalContext()
    if condition == "C":
        provider = kb_provider if kb_provider is not None else DEFAULT_KB_PROVIDER
        kb = provider.get()
        if kb is None:
            notes.append(
                "retrieval unavailable, so this run behaved like condition B: "
                + str(provider.error or "index not built")
            )
        else:
            retrieval = retrieve_for_jd(prepared.jd_clean, kb=kb)
            notes.extend(retrieval.notes)
    elif condition == "B":
        notes.append("condition B: no retrieved notes were used (model only)")

    # ---- posting analysis -------------------------------------------------
    analysis, analysis_notes = analyse_jd(
        prepared.jd_clean,
        profile_clean=prepared.profile_clean,
        client=client,
        condition=condition,
    )
    notes.extend(analysis_notes)

    # ---- facts + guards ---------------------------------------------------
    facts = field_map.extract_facts(
        request.profile,
        request.authorised_modules,
        prepared.rendered,
        jd_text=prepared.jd_clean,
    )
    guard = FabricationGuard(prepared.profile_clean)
    narrative_guard = NarrativeGuard(prepared.profile_clean)

    # ---- one model call for the drafts (B and C) --------------------------
    model_entries: dict[str, dict[str, Any]] = {}
    overall_suggestions: list[str] = []
    model_risks: list[str] = []
    if condition != "A" and fillable:
        try:
            result = client.complete_json(
                system=prompts.WEBFORM_SYSTEM,
                user=prompts.webform_user(
                    candidate_block=wrap_untrusted(
                        prepared.profile_clean, label="CANDIDATE_PROFILE"
                    ),
                    jd_block=(
                        wrap_untrusted(prepared.jd_clean, label="JOB_DESCRIPTION")
                        if prepared.jd_clean.strip()
                        else ""
                    ),
                    field_list_block=field_list_block(fillable),
                ),
                task="webform",
                stub_input={
                    "fields": [
                        {"field_id": f.field_id, "fact_key": f.fact_key} for f in fillable
                    ],
                    "facts": field_map.facts_for_stub(facts),
                    "profile_text": prepared.profile_clean,
                    "jd_text": prepared.jd_clean,
                },
            )
            payload = result.content or {}
            model_entries = _model_field_map(payload)
            overall_suggestions = [
                str(s).strip() for s in (payload.get("overall_suggestions") or []) if str(s).strip()
            ][:8]
            model_risks = [
                str(s).strip() for s in (payload.get("risk_flags") or []) if str(s).strip()
            ][:8]
            mode = result.mode
            model_name = result.model
        except LLMError as exc:
            notes.append(f"the model call failed, so every field fell back to your profile: {exc}")
            mode = "offline_stub" if client.offline else "live_api"
            model_name = "offline-deterministic-stub" if client.offline else client.cfg.model
    else:
        if condition != "A" and not fillable:
            notes.append("there was nothing the assistant is allowed to fill, so no model call was made")
        mode = "offline_stub" if client.offline else "live_api"
        model_name = "offline-deterministic-stub" if client.offline else client.cfg.model

    # ---- decide every field, including the ones we refuse ----------------
    suggestions: list[FieldSuggestion] = []
    risks: list[str] = list(model_risks)

    for field in fields:
        if not field.fillable:
            suggestions.append(
                FieldSuggestion(
                    field_id=field.field_id,
                    label=field.label or field.name or field.field_id,
                    type=field.type,
                    required=field.required,
                    max_length=field.max_length,
                    tag=field.tag,
                    selector=field.selector,
                    # No value is echoed for a control we never write to. A hidden
                    # input's value is a CSRF token and a submit button's is its
                    # caption, so neither is the user's answer; copying them into
                    # the response would put non-user data into the panel's
                    # persisted drafts for no benefit. (`already_filled` is False
                    # for these anyway - see `field_map.normalise_fields`.)
                    current_value="",
                    already_filled=False,
                    options=list(field.options),
                    suggested_value=None,
                    missing=False,
                    sensitive_skipped=field.sensitive,
                    needs_user_confirmation=False,
                    fillable=False,
                    confidence=0.0,
                    message=field.skip_reason,
                    reasons=[field.skip_reason],
                )
            )
            continue

        entry = model_entries.get(field.field_id, {})
        proposal = entry.get("suggested_value")
        proposal_text = None if proposal is None else str(proposal).strip()
        if proposal_text == "":
            proposal_text = None

        # Condition A has no model, so the deterministic fact is the whole answer.
        if condition == "A":
            proposal_text = None
            model_confidence = None
        else:
            model_confidence = _as_confidence(entry.get("confidence"))
            if proposal_text is None and model_confidence is not None:
                # The model declined the field; its confidence for a null value
                # is not evidence about anything, so it must not become one.
                model_confidence = None

        fact = facts.get(field.fact_key) if field.fact_key else None
        evidence = _evidence_for_field(
            field, condition=condition, retrieval=retrieval, fact=fact
        )

        suggestion, field_risks = _decide_field(
            field,
            proposed=proposal_text,
            model_confidence=model_confidence,
            model_source=str(entry.get("source") or ""),
            jd_relevance=str(entry.get("jd_relevance") or ""),
            model_message=str(entry.get("message") or ""),
            fact=fact,
            evidence=evidence,
            guard=guard,
            narrative_guard=narrative_guard,
            cfg=cfg,
            condition=condition,
            overwrite_filled=request.overwrite_filled,
        )
        suggestions.append(suggestion)
        risks.extend(field_risks)

    # A posting that asks for something nothing in the profile answers is the
    # single most useful warning this assistant can give.
    if analysis.missing_from_user_profile:
        risks.append(
            "the posting asks for requirements your authorised profile does not evidence: "
            + ", ".join(analysis.missing_from_user_profile[:6])
        )

    counts = GenerateCounts(
        total=len(suggestions),
        suggestion_offered=sum(1 for s in suggestions if s.suggested_value is not None),
        withheld_low_confidence=sum(
            1 for s in suggestions if s.abstained and s.suggested_value is None
        ),
        missing=sum(1 for s in suggestions if s.missing),
        sensitive_skipped=sum(1 for s in suggestions if s.sensitive_skipped),
        already_filled=sum(1 for s in suggestions if s.already_filled),
        needs_confirmation=sum(1 for s in suggestions if s.needs_user_confirmation),
        not_fillable=sum(1 for s in suggestions if not s.fillable),
    )

    if not fillable and considered:
        notes.append("every fillable control on this page is either sensitive or already answered")
    if not considered:
        notes.append("no fillable control was found on this page")
    if mode == "offline_stub":
        notes.append(
            "offline mode: drafts came from the deterministic rule-based stub, not a model. "
            "This exercises the wiring; it is not evidence about answer quality."
        )

    privacy = PrivacyEcho(
        authorised_modules=list(request.authorised_modules),
        used_modules=list(prepared.rendered.used_modules),
        dropped_modules=list(prepared.rendered.dropped_modules),
        in_memory_only=True,
        persisted=False,
    )

    response = GenerateResponse(
        run_id=run_id,
        mode=mode,
        model=model_name,
        condition=condition,
        jd_analysis=analysis,
        overall_suggestions=overall_suggestions,
        risk_flags=risks,
        fields=suggestions,
        counts=counts,
        privacy=privacy,
        notes=notes,
    )
    _maybe_log(response, request, prepared)
    return response


# --------------------------------------------------------------------------- #
# Optional, opt-in, fingerprinted action log
# --------------------------------------------------------------------------- #


def _maybe_log(
    response: GenerateResponse, request: GenerateRequest, prepared: PreparedInputs
) -> None:
    """Write a fingerprinted record - only when explicitly enabled.

    Default is OFF, so out of the box nothing about a user's application reaches
    the disk. When `RJD_SERVER_LOG=1`, the record still contains no user text:
    counts and sha256 prefixes only, the same convention `src/logging_utils.py`
    enforces for evaluation runs. A `jd_url` is recorded as a hash rather than a
    string, because a URL routinely carries an applicant identifier.
    """
    if os.getenv("RJD_SERVER_LOG", "0").strip() not in {"1", "true", "yes", "on"}:
        return
    try:
        import hashlib

        def fp(text: str) -> dict[str, Any]:
            return {
                "chars": len(text or ""),
                "sha256_8": hashlib.sha256((text or "").encode("utf-8")).hexdigest()[:8],
            }

        record = {
            "run_id": response.run_id,
            "ts": time.time(),
            "mode": response.mode,
            "model": response.model,
            "condition": response.condition,
            "counts": response.counts.model_dump(),
            "authorised_modules": request.authorised_modules,
            "used_modules": response.privacy.used_modules,
            "dropped_modules": response.privacy.dropped_modules,
            "fields_in": len(request.fields),
            "profile": fp(prepared.profile_clean),
            "jd": fp(prepared.jd_clean),
            "jd_url": fp(request.jd_url),
            "risk_flags": len(response.risk_flags),
        }
        path = config.ROOT / "artifacts" / "agent_actions.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:  # noqa: BLE001 - logging must never break a request
        pass


__all__ = [
    "DEFAULT_KB_PROVIDER",
    "KnowledgeBaseProvider",
    "NarrativeGuard",
    "PreparedInputs",
    "RESUME_CONFIRM_LINE",
    "RESUME_FIELD_MAP",
    "RetrievalContext",
    "analyse_jd",
    "extract_profile_from_text",
    "field_list_block",
    "fit_to_length",
    "generate",
    "match_option",
    "new_client",
    "prepare_inputs",
    "retrieve_for_jd",
    "scan",
]
