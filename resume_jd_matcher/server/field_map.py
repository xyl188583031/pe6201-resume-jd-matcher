"""Web-form field classification, profile rendering and deterministic facts.

Three jobs, all of them deterministic and all of them browser-free so they can
be unit-tested without a Chrome instance:

1. `normalise_fields` - turn the raw DOM fingerprint from the content script
   into classified fields: stable id, category, the profile fact it maps onto,
   and whether it is a field we must refuse to touch.
2. `render_profile` - turn the user's authorised modules into a
   resume-shaped text block. **This text is both the model's input and the
   fabrication guard's haystack.** That identity is the point: a value can only
   survive the guard if it was present in the authorised rendering, so an
   un-ticked module cannot leak into an answer even if the client sends it.
3. `extract_facts` - the deterministic value for each fact key, so condition A
   (no model) and the offline stub both have real values to work with. Personal
   and education facts come from `src/rules/fields.py` run over the rendered
   text; the handful of extra keys are read from the structured input directly.
   Reusing the extractor keeps one definition of "what a university name looks
   like" for the evaluation path and the browser path.

Everything here reads only what the caller passes in. Nothing touches disk, the
network, the clock or the DOM.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any, Iterable

from src.rules.fields import extract_fields, rank_skills

from server.schemas import MODULE_NAMES, NormalizedField, RawField

# ---------------------------------------------------------------------------
# Control types we never write into.
#
# The task names hidden / submit / button and decoration. Four more are added
# here, all in the same direction (refuse more, never fewer):
#   reset   - clears the form
#   image   - a submit button rendered as an image
#   file    - a file picker; we have no file and must not synthesise one
#   password- a credential, not application content
# A field we refuse to fill costs the user a moment; a field we fill wrongly can
# cost them the application. The asymmetry decides every borderline case here.
# ---------------------------------------------------------------------------
SKIPPED_TYPES: dict[str, str] = {
    "hidden": "hidden input - not a visible form field",
    "submit": "submit control - the assistant never submits",
    "button": "button control - not a data field",
    "reset": "reset control - would clear the form",
    "image": "image submit control - the assistant never submits",
    "file": "file upload - no file can be synthesised",
    "password": "password field - never filled",
}


# ---------------------------------------------------------------------------
# Attributes that make a control unwritable, whatever its type.
#
# Separate from SKIPPED_TYPES because these are *attributes*: SKIPPED_TYPES is
# consulted as `control_type in SKIPPED_TYPES`, and an attribute cannot be
# expressed that way.
#
# Why refuse a locked box at all. `readonly` does **not** stop a script assigning
# `.value` - the DOM accepts it, and that is precisely the reason the rule has to
# be explicit. A control the page has locked is one the *user* cannot edit, so a
# value written into it is a change they cannot review, correct or undo; and a
# locked box is normally filled by the page's own script, which a write would
# silently overwrite. Round 2, report.md section 5 row 2.
#
# `disabled` is the same mistake one step further out, and it was closed by
# construction rather than after an observation: no form in the matrix carried a
# disabled control until round 3 added one, so this is a *predicted* failure
# whose fix is measured, not a failure that was ever seen. What decides it is the
# asymmetry the rest of this file is written to - a field we refuse to fill costs
# the user a moment; a field we fill into a control the page will not submit
# costs them the application. Round 3, report.md section 6.
#
# Two boundaries in each case, both in the same direction: the content script
# never reads such a value and refuses to write to it (`isReadonlyControl` /
# `isDisabledControl` in `extension/src/content.ts`), and this table stops the
# server from offering one.
# ---------------------------------------------------------------------------
SKIPPED_ATTRIBUTES: dict[str, str] = {
    "readonly": (
        "readonly control - the page locked it, so a value written here could not be "
        "edited or confirmed"
    ),
    "disabled": (
        "disabled control - the page switched it off, so a value written here would "
        "neither be editable nor submitted"
    ),
}

#: `SKIPPED_ATTRIBUTES` inverted: the skip reasons that come from an *attribute*
#: rather than from a control type. A control we may not write to must also not
#: have its value carried across the boundary - see `normalise_fields`.
_SKIPPED_ATTRIBUTE_REASONS = frozenset(SKIPPED_ATTRIBUTES.values())


# ---------------------------------------------------------------------------
# Extremely sensitive fields (task section 5.1).
#
# These are government-document numbers. The rule is absolute: no value is ever
# generated, guessed or transmitted, and the field is reported to the UI so the
# user is told to type it themselves.
#
# Two deliberate calls, both documented in server/README.md:
#   * driving-licence number is included, because it is the same class of
#     government-issued identifier as a passport number;
#   * `student id`, `application id`, `candidate reference` are explicitly NOT
#     sensitive - they are institution- or employer-issued and commonly asked
#     for, and blocking them would suppress useful answers.
# ---------------------------------------------------------------------------
SENSITIVE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("passport number", re.compile(r"\bpassport\b", re.I)),
    # The spellings a real form uses for a national identity number. The first
    # alternative covers "National ID" / "National Identification Number" /
    # "National Identity Card"; the second covers a bare "Identification Number",
    # which is the same document - and which a narrower pattern missed entirely,
    # along with the longest official spelling.
    (
        "national identity number",
        re.compile(
            r"\bnational\s+(id|identification|identity)\b"
            r"|\bidentification\s+(number|no)\b"
            r"|\bidentity\s+(card|number|no)\b"
            r"|\bid\s+(card|number|no|num)\b",
            re.I,
        ),
    ),
    # `my\s*kad` rather than `mykad`: `normalise_text` splits camelCase, so the
    # write-up "MyKad" arrives here as "my kad" and a rigid pattern would miss it.
    ("national identity number", re.compile(r"\bnric\b|\bmy\s*kad\b|\baadhaar\b|\baadhar\b|\bpan\s+card\b", re.I)),
    ("social security number", re.compile(r"\b(ssn|social\s+security)\b", re.I)),
    ("residence permit number", re.compile(r"\b(residence|resident)\s+permit\b", re.I)),
    ("tax identification number", re.compile(r"\btax\s+(id|identification|file\s+number)\b|\btin\b", re.I)),
    ("driving licence number", re.compile(r"\b(driving|driver'?s?)\s+licen[cs]e\b", re.I)),
    ("national identity number", re.compile(r"身份证|护照|证件号|證件號", re.I)),
)

#: Patterns that look like an id but are safe. Checked BEFORE `SENSITIVE_PATTERNS`.
SAFE_ID_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"\b(student|matriculation|matric|enrol?ment|application|candidate|reference|"
        r"requisition|posting|order|ticket|employee|staff)\s*(id|no|number|ref)\b",
        re.I,
    ),
)


# ---------------------------------------------------------------------------
# label -> (category, profile module, fact key)
#
# Ordered: the FIRST match wins, so specific patterns are listed before general
# ones. "Company name" therefore resolves to the internship employer before the
# general `\bname\b` fallback can see it.
#
# `module=None` marks a fact that is not owned by one module (skills, and the
# narrative fields), or no fact at all. Narrative fields are still sent to the
# model - see the module docstring; the model may ground them in any authorised
# section, and the guard then checks it against exactly those sections.
# ---------------------------------------------------------------------------
_FIELD_MAP: tuple[tuple[str, str | None, str | None, re.Pattern[str]], ...] = (
    # --- contact / personal ------------------------------------------------
    ("personal", "personal_info", "email", re.compile(r"\be ?mail\b", re.I)),
    ("personal", "personal_info", "phone", re.compile(r"\b(phone|mobile|telephone|contact number|cell(ular)?|contact no)\b", re.I)),
    ("personal", "personal_info", "linkedin", re.compile(r"\blinked ?in\b", re.I)),
    ("personal", "personal_info", "github", re.compile(r"\bgit ?hub\b", re.I)),
    ("personal", "personal_info", "portfolio", re.compile(r"\b(portfolio|personal (web ?site|site|page)|homepage)\b", re.I)),
    ("personal", "personal_info", "location", re.compile(r"\b(location|city|country|address|residence|based in|where are you based)\b", re.I)),
    ("personal", "personal_info", "full_name", re.compile(r"\b(full ?name|applicant name|your name|candidate name|given name|first name|last name|surname|family name)\b", re.I)),
    # --- education ---------------------------------------------------------
    ("education", "education", "education_school", re.compile(r"\b(university|institution|school|college|alma mater)\b", re.I)),
    ("education", "education", "graduation_year", re.compile(r"\b(graduation|graduating|class of|expected (graduation|completion)|completion year)\b", re.I)),
    ("education", "education", "gpa", re.compile(r"\b(gpa|grade point average|grade average)\b", re.I)),
    ("education", "education", "education_degree", re.compile(r"\b(degree|qualification|level of study)\b", re.I)),
    ("education", "education", "education_major", re.compile(r"\b(major|discipline|programme|program of study|field of study|speciali[sz]ation)\b", re.I)),
    # --- experience --------------------------------------------------------
    # `experience` and `project` each hold two different kinds of field, and the
    # category is what decides which evidence judges them (see
    # `services._evidence_for_field`). An employer, a job title, a period or a
    # project name is a literal the authorised profile either holds or does not -
    # the posting has no bearing on it. A summary has to be argued from the
    # posting. Treating them alike let the posting's retrieval score decide
    # whether the candidate's own employer could be written down: the same
    # control, from the same source and the same profile, came out `offered`
    # under a matched posting and `abstained` under a cross-domain one. So the
    # fact-shaped sub-fields get categories of their own (`experience_fact`,
    # `project_fact`) and the narrative ones stay in the tailored pair. Round 3,
    # report.md section 5 row 4 (finding 7a).
    ("experience_fact", "internship", "internship_employer", re.compile(r"\b(employer|company( name)?|organi[sz]ation|firm)\b", re.I)),
    ("experience_fact", "internship", "internship_title", re.compile(r"\b(job title|position|role title|designation|current (title|role))\b", re.I)),
    ("experience_fact", "internship", "internship_dates", re.compile(r"\b(internship|employment|work)\s+(start|end|period|dates?)\b", re.I)),
    ("experience", "internship", "internship_summary", re.compile(r"\b(work experience|employment history|internship experience|describe your (work|role|internship))\b", re.I)),
    # --- projects ----------------------------------------------------------
    ("project_fact", "projects", "project_name", re.compile(r"\bproject (name|title)\b", re.I)),
    ("project", "projects", "project_summary", re.compile(r"\b(project (description|summary|details)|describe (a )?project|portfolio project)\b", re.I)),
    # --- skills ------------------------------------------------------------
    ("skills", None, "top_skills", re.compile(r"\b(skills|technical skills|key skills|competenc(y|ies)|areas of expertise|core strengths)\b", re.I)),
    # --- narrative: no single fact; the model drafts from the whole profile --
    ("narrative", None, None, re.compile(
        r"\b(cover letter|motivation|why (do you|you) want|why this (role|company|position|team)|"
        r"tell us about yourself|introduce yourself|personal statement|additional information|"
        r"anything else|message to|statement of purpose|self introduction)\b",
        re.I,
    )),
)

#: Last-resort mapping for a field that says only "name" / "your details".
_FALLBACK_NAME = re.compile(r"\b(name)\b", re.I)
_FALLBACK_NAME_EXCLUDE = re.compile(
    r"\b(company|employer|school|university|college|project|reference|user|file|nick|host|"
    r"first|last|given|family|surname)\b",
    re.I,
)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def normalise_text(text: str) -> str:
    """Lowercase and turn every separator into a space.

    Required before any word-boundary match, because `\\b` does not fire around
    `_`: the DOM attribute `passport_number` would otherwise fail a `\\bpassport\\b`
    test even though it plainly is one. Separators `_ - . / []() | , ; :` all
    become spaces, so `passport_number`, `Passport No.` and `passport-number` are
    the same string.

    Two word-splits are also applied, because DOM attributes are routinely
    camelCase and this is *not* a cosmetic concern - it is the difference between
    refusing to touch a passport field and happily sending it to a third party:

        PassportNo    -> passport no    (tested: was 'passportno', not detected)
        NRICNumber    -> nric number    (tested: was 'nricnumber', not detected)
        idNumber      -> id number      (tested: was 'idnumber', not detected)

    The first rule splits lower/digit -> Upper (`PassportNo`, `studentId`), the
    second splits an acronym run from the word after it (`NRICNumber`). Between
    them, matching gets *more* sensitive for camelCase input and is unchanged for
    everything already spaced, which is the safe direction for a blocklist.
    """
    cleaned = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", text or "")
    cleaned = re.sub(r"(?<=[A-Z])(?=[A-Z][a-z])", " ", cleaned)
    cleaned = re.sub(r"[_\-.\[\]()/|,;:]+", " ", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip().lower()


def labelish(field: RawField) -> str:
    """The text we classify a field by: everything the user can see or DevTools would.

    `section_context` is deliberately **not** part of this. Section text is not a
    name, and folding a legend in here would let one section heading reclassify
    every control inside it - the exact failure this file's rule ordering exists
    to prevent ("Company name" must beat a section called "Employer details").
    The context is consulted in `classify`, for one decision only.
    """
    return normalise_text(
        " ".join(
            [
                field.label,
                field.placeholder,
                field.aria_label,
                field.help_text,
                field.name,
                field.id,
            ]
        )
    )


def compute_field_id(field: RawField, *, index: int = 0) -> str:
    """A stable id from the control's identifying attributes, per section 4.

    Stability matters more than readability: the extension stores the user's
    confirmations and edits against these ids, so a re-scan of the same page has
    to produce the same id or the user's edits appear to vanish.

    `tag` is deliberately NOT part of the basis. It used to be, which meant a
    control with no name/id/label/placeholder still hashed - to the hash of the
    literal string "input" - so `wf_anon_NNN` was unreachable in practice and a
    page of anonymous controls collapsed onto one id plus order-dependent `-2`,
    `-3` suffixes. `tag` identifies nothing anyway: every text box on the page
    shares it.
    """
    parts = [field.name, field.id, field.label, field.placeholder]
    basis = "|".join(p.strip() for p in parts)
    if not basis.replace("|", "").strip():
        return f"wf_anon_{index:03d}"
    digest = hashlib.sha1(basis.encode("utf-8")).hexdigest()[:12]
    return f"wf_{digest}"


def detect_sensitive(field: RawField) -> tuple[bool, str]:
    """Is this a government-document-number field?

    Safe ids are checked first so that a "Student ID" is not caught by the
    generic `id number` rule.
    """
    text = labelish(field)
    if not text:
        return False, ""
    for pattern in SAFE_ID_PATTERNS:
        if pattern.search(text):
            return False, ""
    for label, pattern in SENSITIVE_PATTERNS:
        if pattern.search(text):
            return True, f"looks like a {label}; never generated, never transmitted"
    return False, ""


def classify(field: RawField) -> tuple[str, str | None, str | None]:
    """Return (category, module, fact_key) for one field.

    One of the two places `section_context` is read (the other is the value drop
    in `normalise_fields`), and it is read for one decision only: whether the
    ambiguous `\bname\b` fallback may fire.
    """
    text = labelish(field)
    if not text:
        return "unknown", None, None
    for category, module, fact_key, pattern in _FIELD_MAP:
        if pattern.search(text):
            return category, module, fact_key
    if _FALLBACK_NAME.search(text) and not _FALLBACK_NAME_EXCLUDE.search(text):
        # A control that says only "Name" is the candidate's own name - *unless*
        # the section it sits in names a different entity. "Employer details" is
        # that evidence, and refusing is the honest reading of it: the candidate's
        # name is certainly wrong in an employer box, and the employer's name is
        # only a guess from a heading. Round 2, report.md section 5 row 1.
        context = normalise_text(field.section_context)
        if context and _FALLBACK_NAME_EXCLUDE.search(context):
            return "unknown", None, None
        return "personal", "personal_info", "full_name"
    return "unknown", None, None


# --------------------------------------------------------------------------- #
# 1. normalise
# --------------------------------------------------------------------------- #


def normalise_fields(raw_fields: Iterable[RawField]) -> list[NormalizedField]:
    """Classify a page's controls into the fields the assistant will consider.

    Fields that are not fillable are still returned, with `fillable=False` and a
    `skip_reason`. Dropping them silently would make the extension's "nothing
    happened for that field" indistinguishable from a bug.
    """
    out: list[NormalizedField] = []
    seen_ids: dict[str, int] = {}

    for index, field in enumerate(raw_fields):
        field_id = (field.field_id or "").strip() or compute_field_id(field, index=index)
        # Guarantee uniqueness: two controls can legitimately share a name+label
        # (a billing and a shipping email), and duplicate ids would make the
        # user's per-field edits collide.
        if field_id in seen_ids:
            seen_ids[field_id] += 1
            field_id = f"{field_id}-{seen_ids[field_id]}"
        else:
            seen_ids[field_id] = 1

        category, module, fact_key = classify(field)
        sensitive, sensitive_reason = detect_sensitive(field)

        control_type = normalise_text(field.type).replace(" ", "") or "text"
        tag = (field.tag or "input").strip().lower()
        skip_reason = ""
        if tag == "input" and control_type in SKIPPED_TYPES:
            skip_reason = SKIPPED_TYPES[control_type]
        elif tag not in {"input", "textarea", "select", "contenteditable"}:
            skip_reason = f"unsupported control <{tag}>"
        elif tag in {"input", "textarea"} and field.readonly:
            # Attribute-based, so it cannot live in SKIPPED_TYPES. Checked after
            # the type rules on purpose: a locked password box is reported as a
            # password box, which is the more specific fact. Round 2, report.md
            # section 5 row 2.
            skip_reason = SKIPPED_ATTRIBUTES["readonly"]
        elif tag in {"input", "textarea", "select"} and field.disabled:
            # Same family as `readonly`, checked after it so the more specific
            # attribute still wins when a control carries both - and after the
            # type rules above, which win over both because "this is a password
            # box" is the more dangerous fact to report. `disabled` is valid on a
            # `<select>` too, so this branch is one tag wider. Round 3, report.md
            # section 6.
            skip_reason = SKIPPED_ATTRIBUTES["disabled"]
        # A control we may not write to has a value that is not ours to carry, for
        # the same reason a document number is not: nothing downstream uses it -
        # the control is never filled - so this removes a value from the wire at
        # no cost.
        value_is_not_ours = sensitive or skip_reason in _SKIPPED_ATTRIBUTE_REASONS

        # Only a control we may actually write to can be "already filled by the
        # user". Gating on `fillable` matters more than it looks: an
        # `<input type="submit" value="Submit application">` carries its *caption*
        # in `value`, and a hidden input carries a CSRF token there, so testing
        # the raw value reported four already-answered fields on a page where the
        # user had typed nothing - and the panel would then say so.
        already_filled = bool((field.current_value or "").strip()) and not skip_reason

        out.append(
            NormalizedField(
                field_id=field_id,
                label=(field.label or field.aria_label or field.placeholder or field.name or "").strip(),
                tag=tag,
                type=control_type,
                name=field.name,
                id=field.id,
                required=bool(field.required),
                max_length=field.max_length,
                options=list(field.options or []),
                help_text=field.help_text,
                # Two kinds of value are dropped here, at the one place both
                # `/scan` and `/generate` build a field from the page, rather than
                # at each response site - because a single missed site puts the
                # value in the panel's persisted drafts:
                #   * a sensitive control's value is a government document number;
                #   * a page-locked value is page-managed and can never be edited
                #     by the user, and a page-disabled one cannot even be
                #     submitted (round 2, report.md section 5 row 2; round 3,
                #     section 6).
                # `already_filled` is computed above, from the raw value, so the
                # "you typed something" signal survives without the value doing so.
                current_value=("" if value_is_not_ours else field.current_value),
                selector=field.selector,
                already_filled=already_filled,
                fillable=not skip_reason,
                skip_reason=skip_reason,
                category=category,
                module=module,
                fact_key=fact_key,
                sensitive=sensitive,
                sensitive_reason=sensitive_reason,
            )
        )
    return out


# --------------------------------------------------------------------------- #
# 2. render the authorised profile
# --------------------------------------------------------------------------- #

_PERSONAL_LABELS: dict[str, str] = {
    "full_name": "Full Name",
    "name": "Full Name",
    "email": "Email",
    "phone": "Phone",
    "location": "Location",
    "linkedin": "LinkedIn",
    "github": "GitHub",
    "portfolio": "Portfolio",
}

_MODULE_HEADINGS: dict[str, str] = {
    "personal_info": "PERSONAL INFORMATION",
    "education": "EDUCATION",
    "internship": "INTERNSHIP EXPERIENCE",
    "projects": "PROJECTS",
}


@dataclass
class RenderedProfile:
    text: str
    module_texts: dict[str, str]
    used_modules: list[str]
    dropped_modules: list[str]
    empty_modules: list[str]

    @property
    def has_content(self) -> bool:
        return bool(self.text.strip())


def _scalar(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, (list, tuple)):
        return ", ".join(_scalar(v) for v in value if v not in (None, ""))
    return str(value).strip()


def _render_records(items: Any) -> str:
    """Render a list of records as readable resume bullets."""
    if isinstance(items, dict):
        items = [items]
    if isinstance(items, str):
        return items.strip()
    if not isinstance(items, (list, tuple)):
        return _scalar(items)

    lines: list[str] = []
    for item in items:
        if isinstance(item, str):
            if item.strip():
                lines.append(f"- {item.strip()}")
            continue
        if not isinstance(item, dict):
            continue
        head_parts = [
            _scalar(item.get("title") or item.get("degree") or item.get("name")),
            _scalar(item.get("employer") or item.get("company") or item.get("school") or item.get("organisation")),
        ]
        head_parts = [p for p in head_parts if p]
        head = " at ".join(head_parts) if len(head_parts) == 2 else (head_parts[0] if head_parts else "")

        start = _scalar(item.get("start") or item.get("start_date"))
        end = _scalar(item.get("end") or item.get("end_date"))
        period = f"{start} - {end}".strip(" -") if (start or end) else ""
        if period:
            head = f"{head} ({period})" if head else f"({period})"

        # Education renders as one prose line so `src/rules/fields.py` can read a
        # degree and an institution out of it exactly as it would from a resume.
        if item.get("degree") or item.get("school") or item.get("major"):
            degree = _scalar(item.get("degree"))
            major = _scalar(item.get("major"))
            school = _scalar(item.get("school"))
            prose_parts = []
            if degree and major:
                prose_parts.append(f"{degree} in {major}")
            elif degree:
                prose_parts.append(degree)
            elif major:
                prose_parts.append(major)
            if school:
                prose_parts.append(school)
            if period:
                prose_parts.append(period)
            gpa = _scalar(item.get("gpa"))
            if gpa:
                prose_parts.append(f"GPA {gpa}")
            if prose_parts:
                lines.append("- " + ", ".join(prose_parts))
        elif head:
            lines.append(f"- {head}")

        for key in ("summary", "detail", "description", "role"):
            value = _scalar(item.get(key))
            if value:
                lines.append(f"  {value}")
        highlights = item.get("highlights")
        if isinstance(highlights, (list, tuple)):
            for note in highlights:
                text = _scalar(note)
                if text:
                    lines.append(f"  - {text}")
        # Any remaining scalar keys are rendered verbatim, so a user-defined
        # field is not silently dropped from the profile the model sees.
        for key, value in item.items():
            if key in {
                "title", "degree", "name", "employer", "company", "school", "organisation",
                "start", "start_date", "end", "end_date", "summary", "detail", "description",
                "role", "highlights", "major", "gpa",
            }:
                continue
            text = _scalar(value)
            if text:
                lines.append(f"  {key.replace('_', ' ').title()}: {text}")
    return "\n".join(lines)


def render_profile(
    profile: dict[str, Any], authorised_modules: Iterable[str]
) -> RenderedProfile:
    """Build the model input from the authorised modules only.

    A module present in `profile` but absent from `authorised_modules` is not
    rendered at all and is reported in `dropped_modules`. This is the server-side
    half of the authorisation rule (task section 3): the browser must not send it,
    and the server refuses it if it does.
    """
    authorised = [m for m in MODULE_NAMES if m in set(authorised_modules)]
    provided = {k: v for k, v in (profile or {}).items() if k in MODULE_NAMES and v not in (None, "", [], {})}
    dropped = [m for m in MODULE_NAMES if m in provided and m not in authorised]

    module_texts: dict[str, str] = {}
    empty: list[str] = []
    blocks: list[str] = []

    for module in authorised:
        value = provided.get(module)
        if value in (None, "", [], {}):
            empty.append(module)
            continue

        if module == "personal_info" and isinstance(value, dict):
            lines = []
            for key, raw in value.items():
                text = _scalar(raw)
                if not text:
                    continue
                lines.append(f"{_PERSONAL_LABELS.get(key, key.replace('_', ' ').title())}: {text}")
            body = "\n".join(lines)
        else:
            body = _render_records(value)

        if not body.strip():
            empty.append(module)
            continue

        module_texts[module] = body
        blocks.append(f"{_MODULE_HEADINGS[module]}\n{body}")

    return RenderedProfile(
        text="\n\n".join(blocks),
        module_texts=module_texts,
        used_modules=list(module_texts),
        dropped_modules=dropped,
        empty_modules=empty,
    )


# --------------------------------------------------------------------------- #
# 3. deterministic facts
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Fact:
    key: str
    value: str
    confidence: float
    source: str
    module: str


#: Mechanism-based, not calibrated - the same convention `src/rules/fields.py`
#: uses. `summary`-type facts score low because they are prose lifted verbatim
#: rather than a field that either is or is not present.
_EXTRA_CONFIDENCE: dict[str, float] = {
    "location": 0.70,
    "linkedin": 0.80,
    "github": 0.80,
    "portfolio": 0.70,
    "gpa": 0.75,
    "internship_employer": 0.80,
    "internship_title": 0.80,
    "internship_dates": 0.70,
    "internship_summary": 0.55,
    "project_name": 0.75,
    "project_summary": 0.55,
}

_PERSONAL_LABELLED = {
    "linkedin": re.compile(r"\blinked ?in\b\s*[:\-]?\s*(\S[^\n]*)", re.I),
    "github": re.compile(r"\bgit ?hub\b\s*[:\-]?\s*(\S[^\n]*)", re.I),
    "portfolio": re.compile(r"\b(?:portfolio|personal web ?site|homepage)\b\s*[:\-]?\s*(\S[^\n]*)", re.I),
    "location": re.compile(r"\blocation\b\s*[:\-]?\s*([^\n]+)", re.I),
}

#: GPA is an education fact, so it is searched in the education rendering rather
#: than the personal one. Getting this wrong made the field silently unavailable
#: even though the user had given it.
_EDUCATION_LABELLED = {
    "gpa": re.compile(r"\bgpa\b\s*[:\-]?\s*([0-9]+(?:\.[0-9]+)?(?:\s*/\s*[0-9]+(?:\.[0-9]+)?)?)", re.I),
}


def _first_record(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, (list, tuple)):
        for item in value:
            if isinstance(item, dict):
                return item
    return {}


def extract_facts(
    profile: dict[str, Any],
    authorised_modules: Iterable[str],
    rendered: RenderedProfile,
    *,
    jd_text: str = "",
) -> dict[str, Fact]:
    """Deterministic fact values, drawn only from the authorised rendering.

    Personal and education facts come from `src/rules/fields.extract_fields` run
    over the rendered text - the same function condition A uses on a resume, so
    the two paths cannot disagree about what an email address looks like. The
    remaining keys are read from the structured input.
    """
    authorised = set(rendered.used_modules)
    facts: dict[str, Fact] = {}

    def put(key: str, value: Any, module: str, confidence: float | None = None) -> None:
        text = _scalar(value)
        if not text:
            return
        facts[key] = Fact(
            key=key,
            value=text,
            confidence=float(
                confidence if confidence is not None else _EXTRA_CONFIDENCE.get(key, 0.6)
            ),
            source=f"{module}.{key}",
            module=module,
        )

    # --- personal + education, via the shared rule extractor -----------------
    if rendered.text.strip():
        extracted = extract_fields(rendered.text, jd_text)
        rule_fields = extracted["fields"]
        rule_conf = extracted["field_confidence"]
        owner = {
            "full_name": "personal_info",
            "email": "personal_info",
            "phone": "personal_info",
            "education_school": "education",
            "education_degree": "education",
            "education_major": "education",
            "graduation_year": "education",
        }
        for key, module in owner.items():
            if module not in authorised:
                continue
            put(key, rule_fields.get(key), module, rule_conf.get(key))

        # `top_skills` is grounded in the UNION of the authorised modules, not in
        # one of them - a skill is evidenced by whichever section mentions it.
        # The fact is therefore attributed to the first authorised module purely
        # so the UI has something to display; the authorisation guarantee comes
        # from the fact that `rendered.text` contains only authorised sections.
        skills = rank_skills(rendered.text, jd_text, limit=3)
        if skills and rendered.used_modules:
            put("top_skills", skills, rendered.used_modules[0], rule_conf.get("top_skills"))

    # --- extra scalar facts -------------------------------------------------
    if "personal_info" in authorised:
        personal_text = rendered.module_texts.get("personal_info", "")
        for key, pattern in _PERSONAL_LABELLED.items():
            match = pattern.search(personal_text)
            if match:
                put(key, match.group(1).strip().strip(",;"), "personal_info")

    if "education" in authorised:
        education_text = rendered.module_texts.get("education", "")
        for key, pattern in _EDUCATION_LABELLED.items():
            match = pattern.search(education_text)
            if match:
                put(key, match.group(1).strip(), "education")

    if "internship" in authorised:
        record = _first_record((profile or {}).get("internship"))
        if record:
            put("internship_employer", record.get("employer") or record.get("company") or record.get("organisation"), "internship")
            put("internship_title", record.get("title") or record.get("role") or record.get("position"), "internship")
            start = _scalar(record.get("start") or record.get("start_date"))
            end = _scalar(record.get("end") or record.get("end_date"))
            period = f"{start} - {end}".strip(" -")
            put("internship_dates", period, "internship", 0.70)
            put("internship_summary", record.get("summary") or record.get("description") or record.get("detail"), "internship")

    if "projects" in authorised:
        record = _first_record((profile or {}).get("projects"))
        if record:
            put("project_name", record.get("name") or record.get("title"), "projects", 0.75)
            put("project_summary", record.get("summary") or record.get("description") or record.get("detail"), "projects")

    return facts


def facts_for_stub(facts: dict[str, Fact]) -> list[dict[str, Any]]:
    """Serialise facts for the offline stub's `stub_input`."""
    return [
        {
            "key": fact.key,
            "value": fact.value,
            "confidence": fact.confidence,
            "source": fact.source,
        }
        for fact in facts.values()
    ]


__all__ = [
    "Fact",
    "RenderedProfile",
    "SAFE_ID_PATTERNS",
    "SENSITIVE_PATTERNS",
    "SKIPPED_ATTRIBUTES",
    "SKIPPED_TYPES",
    "classify",
    "compute_field_id",
    "detect_sensitive",
    "extract_facts",
    "facts_for_stub",
    "labelish",
    "normalise_fields",
    "normalise_text",
    "render_profile",
]
