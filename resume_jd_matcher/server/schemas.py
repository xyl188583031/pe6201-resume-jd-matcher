"""Pydantic v2 request/response models for the local backend.

Naming is aligned with the existing pipeline types on purpose, so a reader can
map a JSON key back to the object that produced it:

    Assessment           -> ConfidenceAssessment (src/pipeline/confidence.py)
    PrefillBundle        -> PrefillBundle        (src/pipeline/prefill.py)
    RunRecord            -> RunRecord            (src/logging_utils.py)

Two things this file is careful about.

1. `FieldSuggestion` is a strict SUPERSET of the schema the task specifies. The
   specified keys are all present, with the specified types and defaults. The
   extra keys (`selector`, `tag`, `current_value`, `already_filled`, `options`,
   `abstained`, `reasons`) exist because the response also has to drive a
   browser extension - it must be able to find the DOM node again and it must be
   able to say *why* a value was withheld. They are additive; a consumer that
   reads only the specified keys is unaffected. `server/README.md` lists which
   keys are specified and which are additive.

2. `suggested_value` is `None` - never `""` - whenever the value is withheld.
   Those are different states: `""` is a value the user could legitimately want
   written into an empty field, `None` means "there is nothing honest to put
   here". Collapsing them would let a skipped passport field look like an
   intentional blank.

3. `RawField` carries three page-side flags beyond the specified keys, each
   pinned to a section of `artifacts/form_matrix/report.md`: `readonly`, because a
   control the page has locked is not fillable and its value is not ours to carry
   (round 2, section 5 row 2); `section_context`, because the text of an enclosing
   `<legend>` or heading is context and may never be used as a field's *name*
   (round 2, section 5 row 1); and `disabled`, the same family as `readonly` one step
   further out (round 3, section 6). All three are documented in place below.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

Condition = Literal["A", "B", "C"]

#: The four independently-authorised profile modules (task section 3).
#: `personal_info` also carries `internship`-free contact fields; the split below
#: is what the authorisation checkboxes map onto.
MODULE_NAMES: tuple[str, ...] = ("personal_info", "internship", "projects", "education")

#: Modules whose entries are a list of records rather than a flat mapping.
LIST_MODULES: tuple[str, ...] = ("internship", "projects", "education")


# --------------------------------------------------------------------- §4 scan


class RawField(BaseModel):
    """One form control as the content script sees it.

    Every attribute here is present in the DOM already; the content script
    fingerprints them rather than interpreting them. Interpretation (is this a
    passport number? is this an email field?) happens on the server, in one
    place, so the rule is testable without a browser.
    """

    field_id: str | None = Field(
        default=None,
        description="Content-script fingerprint. Server recomputes it when absent.",
    )
    tag: str = Field(default="input", description="input | textarea | select | contenteditable")
    type: str = Field(default="text")
    name: str = ""
    id: str = ""
    label: str = ""
    placeholder: str = ""
    aria_label: str = ""
    required: bool = False
    max_length: int | None = None
    options: list[str] = Field(default_factory=list)
    help_text: str = Field(default="", description="Visible text near the control.")
    current_value: str = Field(
        default="",
        description="What the field already holds. The user's own typing outranks the model.",
    )
    #: The page locked this control (`readonly`). Round 2, report.md section 5 row 2.
    #: The content script never reads a locked value and never writes one; this
    #: flag is how the server reaches the same conclusion and marks the control
    #: not-fillable instead of offering an answer nobody could edit.
    readonly: bool = Field(default=False, description="The page marked this control readonly.")
    #: The page disabled this control. Same family as `readonly`, one step
    #: stronger: a disabled control cannot be typed into *and* the page will not
    #: submit it, so a value written here is lost twice over. The content script
    #: never reads its value and never writes one; this flag is the server's
    #: second line of defence, so the control is reported `not_fillable` instead
    #: of being offered an answer nobody could accept. Round 3, report.md
    #: section 6.
    disabled: bool = Field(default=False, description="The page disabled this control.")
    #: Text of the enclosing section (`<legend>`, a heading, a `<caption>`).
    #: **Context, never a name.** `field_map.classify` consults it for exactly one
    #: decision - whether the generic `\bname\b` fallback may fire. Round 2,
    #: report.md section 5 row 1.
    section_context: str = Field(
        default="",
        description="Enclosing section text. Used to disambiguate a name, never to label one.",
    )
    selector: str = Field(default="", description="CSS path the content script can resolve later.")


class ScanRequest(BaseModel):
    url: str = ""
    page_title: str = ""
    fields: list[RawField] = Field(default_factory=list)


class NormalizedField(BaseModel):
    """A `RawField` after the server has classified it."""

    field_id: str
    label: str
    tag: str
    type: str
    name: str = ""
    id: str = ""
    required: bool = False
    max_length: int | None = None
    options: list[str] = Field(default_factory=list)
    help_text: str = ""
    current_value: str = ""
    selector: str = ""

    # --- classification -----------------------------------------------------
    already_filled: bool = False
    fillable: bool = Field(
        default=True, description="False for controls the assistant must not touch."
    )
    skip_reason: str = ""
    category: str = Field(
        default="unknown",
        description="personal | education | experience | project | skills | narrative | unknown",
    )
    module: str | None = Field(
        default=None, description="Profile module this field draws on, when known."
    )
    fact_key: str | None = Field(
        default=None, description="Deterministic fact this field maps onto, when known."
    )
    sensitive: bool = False
    sensitive_reason: str = ""


class ScanCounts(BaseModel):
    total: int = 0
    fillable: int = 0
    required: int = 0
    already_filled: int = 0
    sensitive: int = 0
    skipped: int = 0


class ScanResponse(BaseModel):
    url: str = ""
    page_title: str = ""
    counts: ScanCounts = Field(default_factory=ScanCounts)
    fields: list[NormalizedField] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


# ------------------------------------------------------------- §6 jd_analysis


class JDAnalysis(BaseModel):
    """Exactly the `jd_analysis` object from the task's output schema."""

    job_title: str = ""
    company: str = ""
    location: str = ""
    responsibilities: list[str] = Field(default_factory=list)
    requirements: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    bonus_points: list[str] = Field(default_factory=list)
    missing_from_user_profile: list[str] = Field(default_factory=list)


# ------------------------------------------------------------------ §6 generate


class FieldSuggestion(BaseModel):
    """One field's suggestion.

    Specified keys first, additive keys after the divider comment.
    """

    field_id: str
    label: str = ""
    type: str = "text"
    required: bool = False
    max_length: int | None = None
    suggested_value: str | None = None
    source: str = ""
    jd_relevance: str = ""
    confidence: float = 0.0
    components_present: list[str] = Field(default_factory=list)
    needs_user_confirmation: bool = True
    missing: bool = False
    sensitive_skipped: bool = False
    message: str = ""

    # ---- additive: needed to drive a browser, not part of the specified schema
    tag: str = ""
    selector: str = ""
    current_value: str = ""
    already_filled: bool = False
    options: list[str] = Field(default_factory=list)
    abstained: bool = False
    reasons: list[str] = Field(default_factory=list)
    #: False for a control the assistant must not touch at all (hidden, submit,
    #: reset, file, password, unsupported element). Distinct from "we have no
    #: value for it": the panel must not offer a fill action for a control we
    #: will never write to, and without this flag the only signal was a
    #: human-readable `message`.
    fillable: bool = True

    @field_validator("confidence")
    @classmethod
    def _clamp_confidence(cls, value: float) -> float:
        # Rounded to the same precision the evaluation payloads use
        # (`ConfidenceAssessment.to_payload`), so a browser screenshot and a run
        # log show the same number rather than 0.8500000000000001.
        return round(max(0.0, min(1.0, float(value))), 4)

    @property
    def will_fill(self) -> bool:
        return self.suggested_value is not None and not self.sensitive_skipped


class GenerateCounts(BaseModel):
    """How many fields are in each state.

    `suggestion_offered`, `withheld_low_confidence`, `missing`, `sensitive_skipped`
    and `not_fillable` partition the fields: each one is in exactly one of them.
    `already_filled` is a separate, orthogonal count - a field the user filled can
    also be one we refuse - so it deliberately overlaps the others rather than
    being a sixth exclusive bucket.
    """

    total: int = 0
    suggestion_offered: int = 0
    withheld_low_confidence: int = 0
    missing: int = 0
    sensitive_skipped: int = 0
    already_filled: int = 0
    needs_confirmation: int = 0
    #: Controls the assistant never touches. `/scan` reported this as `skipped`
    #: from the start; `/generate` did not, which left those controls in no
    #: bucket at all and made the response's totals fail to reconcile.
    not_fillable: int = 0


class PrivacyEcho(BaseModel):
    """What the server actually used.

    Returned so the client can prove to the user that un-ticked modules never
    reached the model. `dropped_modules` is non-empty exactly when the client
    sent data for a module it had not authorised - the server strips it and says
    so rather than trusting the client to have scrubbed it.
    """

    authorised_modules: list[str] = Field(default_factory=list)
    used_modules: list[str] = Field(default_factory=list)
    dropped_modules: list[str] = Field(default_factory=list)
    in_memory_only: bool = True
    persisted: bool = False


class GenerateRequest(BaseModel):
    fields: list[RawField] = Field(default_factory=list)
    authorised_modules: list[str] = Field(default_factory=list)
    profile: dict[str, Any] = Field(default_factory=dict)
    jd_text: str = ""
    jd_url: str = Field(
        default="",
        description="Resolved by the client via /jd/fetch; the server will not fetch it here.",
    )
    condition: Condition = "C"
    url: str = ""
    page_title: str = ""
    #: Section 7.3: the user's own typing outranks the model. When this is False
    #: (the default) a field that already holds a value is never given a
    #: suggested value, so the assistant cannot overwrite the user. The client
    #: sets it to True only after the user explicitly asks to regenerate.
    overwrite_filled: bool = False
    #: When the client already holds a scan (identical fingerprint), it may pass
    #: it to skip re-normalisation. Optional; the server re-normalises anyway
    #: when the list is empty.
    scanned_field_ids: list[str] = Field(default_factory=list)

    @field_validator("authorised_modules")
    @classmethod
    def _known_modules(cls, value: list[str]) -> list[str]:
        unknown = [m for m in value if m not in MODULE_NAMES]
        if unknown:
            raise ValueError(
                f"unknown module(s) {unknown}; expected any of {list(MODULE_NAMES)}"
            )
        # de-duplicate, keep declared order
        seen: list[str] = []
        for item in value:
            if item not in seen:
                seen.append(item)
        return seen

    @field_validator("condition", mode="before")
    @classmethod
    def _upper(cls, value: Any) -> Any:
        return value.upper() if isinstance(value, str) else value


class GenerateResponse(BaseModel):
    run_id: str
    mode: str = Field(description="live_api | offline_stub")
    model: str = ""
    condition: str = "C"
    jd_analysis: JDAnalysis = Field(default_factory=JDAnalysis)
    overall_suggestions: list[str] = Field(default_factory=list)
    risk_flags: list[str] = Field(default_factory=list)
    fields: list[FieldSuggestion] = Field(default_factory=list)
    counts: GenerateCounts = Field(default_factory=GenerateCounts)
    privacy: PrivacyEcho = Field(default_factory=PrivacyEcho)
    notes: list[str] = Field(default_factory=list)


# ------------------------------------------------------------------ §2 jd/fetch


class JdFetchRequest(BaseModel):
    url: str
    #: Skip the robots.txt lookup. Only for the user's own intranet docs, where
    #: robots.txt is not the applicable policy. Defaults to respecting robots.txt.
    ignore_robots: bool = False


class JdFetchResponse(BaseModel):
    ok: bool = False
    url: str = ""
    final_url: str = ""
    status: int | None = None
    content_type: str = ""
    title: str = ""
    text: str = ""
    chars: int = 0
    robots_allowed: bool = True
    reason: str = Field(
        default="",
        description=(
            "ok | unsupported_scheme | private_host | robots_disallowed | login_required | "
            "paywall | captcha | blocked | too_large | not_html | timeout | network_error | "
            "http_error"
        ),
    )
    message: str = Field(
        default="",
        description="User-facing. Always tells the user what to do next when ok=False.",
    )


class JdAnalyzeRequest(BaseModel):
    jd_text: str = ""
    jd_url: str = ""
    authorised_modules: list[str] = Field(default_factory=list)
    profile: dict[str, Any] = Field(default_factory=dict)
    condition: Condition = "B"

    @field_validator("condition", mode="before")
    @classmethod
    def _upper(cls, value: Any) -> Any:
        return value.upper() if isinstance(value, str) else value


class JdAnalyzeResponse(BaseModel):
    run_id: str
    mode: str = ""
    model: str = ""
    condition: str = "B"
    jd_analysis: JDAnalysis = Field(default_factory=JDAnalysis)
    privacy: PrivacyEcho = Field(default_factory=PrivacyEcho)
    notes: list[str] = Field(default_factory=list)


# --------------------------------------------------------- §9 extract_resume


class ExtractResumeRequest(BaseModel):
    """Resume text the browser has already extracted from a PDF.

    The PDF itself is never sent. The extension parses it in the page with
    PDF.js and posts only the text, so this request has no file, no multipart
    body and nothing for the server to write to disk - which is what keeps the
    endpoint compatible with H3 (no user text is persisted) without needing a
    separate upload sandbox.
    """

    text: str = Field(default="", description="Plain text extracted from the resume.")


class ExtractResumeResponse(BaseModel):
    """A profile for the user to confirm before it replaces anything.

    `profile` is deliberately the same shape `GenerateRequest.profile` accepts,
    so the panel can store what it is given and send it back unchanged. Nothing
    here is presented as fact: every key in `uncertain_fields` is one the
    extractor is not sure of, and the panel shows them as such.
    """

    profile: dict[str, Any] = Field(default_factory=dict)
    extracted_fields: list[str] = Field(
        default_factory=list,
        description="Dotted paths the extractor filled, e.g. `personal_info.email`.",
    )
    uncertain_fields: list[str] = Field(
        default_factory=list,
        description=(
            "Dotted paths the user should check: the extractor either guessed (its "
            "own mechanism confidence is below the confirmation line) or could not "
            "read the value at all."
        ),
    )
    source: str = Field(
        default="resume_text",
        description="Where the profile came from. `resume_text` means the browser parsed a PDF.",
    )
    notes: list[str] = Field(default_factory=list)


# -------------------------------------------------------------------- §2 health


class HealthResponse(BaseModel):
    status: str = "ok"
    app: str = ""
    version: str = ""
    mode: str = Field(default="", description="live_api | offline_stub")
    model: str = ""
    bind_host: str = ""
    bind_port: int = 0
    auth_required: bool = False
    knowledge_base: dict[str, Any] | None = None
    sensitive_policy: dict[str, Any] = Field(default_factory=dict)
    privacy: dict[str, Any] = Field(default_factory=dict)
    prototype_banner: str = ""
    non_use_notice: str = ""


class ErrorResponse(BaseModel):
    detail: str
    reason: str = ""
