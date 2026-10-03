"""Form-matrix test driver for the browser-assistant path.

Answers one question, with counts rather than adjectives:

    "Once the pipeline is wrapped in a browser assistant, does it still hold up
     under field diversity and profile diversity?"

It drives the *browser assistant's own HTTP contract* - `/scan` then `/generate` -
across a layered sample of six simulated forms, five synthetic resumes and three
synthetic postings, and records what the server decided for every control. It is
not a browser: the content script's DOM extraction is mirrored here in Python so
the matrix can run on a machine with no browser at all. That mirroring is the one
place this script could drift from the product, so it is written to follow
`extension/src/content.ts` line for line (selector, `isFillableControl`,
`resolveLabel` including the leaf-only sibling rule, `resolveHelpText` including
the deliberate exclusion of `<legend>`, `resolveOptions`, `currentValueOf`, the
`NEVER_READ_TYPES` list, and the contenteditable normalisation to
tag="contenteditable"). `extension/scripts/browser_check.mjs` is what verifies the
real content script; this script verifies the server's behaviour given its output.

Round 2 added three mirrored rules, each traceable to a finding in this report:

    * `isSectionLevelText` - a `<legend>` / heading / `<caption>` is section
      *context* and may never be a field's `label` (report section 5 row 1, which is
      the `label` side of README bug 19). The section text travels as
      `section_context` and the server uses it for exactly one decision.
    * `isReadonlyControl` - a locked control is never read and never filled
      (report section 5 row 2).
    * the value-drop rule - a locked control's value is not carried at all.

Round 3 added the third member of that family, `isDisabledControl` - the same
decision one attribute further out, never read and never written (report section
6) - and with it the `email_disabled` control on form_05, so the refusal is
*measured* rather than predicted.

Where the mirror and the product disagree, the mirror is the defect.

What it writes, and where:

    artifacts/form_matrix/runs.jsonl             one line per run, hashes not values
    artifacts/form_matrix/l2_review.md           the human sheet: generated, then hand-filled
    artifacts/form_matrix/report.md              the eight-section report
    artifacts/form_matrix/source_fingerprint.json  sha256 of the files that decide policy
    artifacts/form_matrix/privacy_scan.json      what the plaintext scan looked at

`l2_review.md` is **never overwritten once it carries verdicts**. The generated
question sheet is a starting point, not an artifact: a person fills the verdict
column in, and a later run that clobbered it would destroy the only copy of that
judgement. When the existing file carries verdicts this script writes the fresh
sheet to `l2_review.generated.md` and says so on stdout.

Hard constraints this script is built to respect, each with the check that proves it:

    H1  simulated HTML only .... every run's page URL is a 127.0.0.1 URL, and no
                                 run calls /jd/fetch at all
    H2  never submits .......... no value is ever offered for a submit/button/reset
                                 control; the API exposes no write route; the static
                                 server's access log must contain zero POSTs
    H3  no persisted text ...... only sha256 prefixes and lengths are written; every
                                 artifact is scanned for the source texts before the
                                 run is declared finished
    H4  synthetic data only .... every address in the matrix is on example.com or
                                 example.edu
    H5  no document numbers .... each form carries a canary in an identity control;
                                 the canary must not appear in any response body, and
                                 the control must come back sensitive_skipped
    H6  missing means null ..... every field the server reports as missing carries
                                 suggested_value = null, never ""
    H7  policy untouched ....... sha256 of `src/`'s decision modules and `config.yaml`
                                 is recorded; the abstention threshold is read back and
                                 asserted unchanged
    H8  no timing metric ....... no duration is measured or reported anywhere

Usage:
    python scripts/run_form_matrix.py --verbose
    python scripts/run_form_matrix.py            # exit 0 = every L1 check passed

Exit code is 0 only when every L1 machine check passes. L2 is never auto-graded by
the script: it writes the questions, and a person fills the verdict column in. The
distribution that person produced is *read back* out of `l2_review.md` and asserted
against the one the report quotes, so the report cannot outlive its evidence.
"""

from __future__ import annotations

import argparse
import functools
import hashlib
import json
import os
import re
import socket
import sys
import threading
import time
from dataclasses import dataclass, field as dc_field
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

DATA_DIR = REPO_ROOT / "data" / "test_matrix"
RESUME_DIR = DATA_DIR / "resumes"
JD_DIR = DATA_DIR / "jds"
FORM_DIR = REPO_ROOT / "demo" / "form_matrix"
EXT_DIST = REPO_ROOT / "extension" / "dist"
ARTIFACTS = REPO_ROOT / "artifacts"
OUT_DIR = ARTIFACTS / "form_matrix"

TOKEN = "form-matrix-token"

#: Bait values planted on the simulated pages. Not credentials, not documents:
#: they exist so their absence from every response and every log can be asserted.
CANARY = "E1234567X"              # identity controls in form_01, form_02, form_05
PASSWORD_CANARY = "Sup3rSecret!"  # form_05's password box
PREFILLED_NAME = "Existing Applicant"  # form_05's page-side pre-fill

PROTOTYPE_NOTICE = "Prototype - not for live sites"

CONDITION = "C"  # the RAG path; the matrix asks about retrieval-grounded behaviour

# The change log in report section 8 is three columns wide - round 1, round 2,
# round 3 - and a "before" number cannot be recomputed from the "after" data: the
# whole point is that the data moved. So the two historical columns are recorded
# from the snapshots on disk, and `main` re-derives every one of them from
# `runs_before_round2.jsonl` / `runs_before_round3.jsonl` before printing them. A
# transcription that did not match the records would fail a machine check, not
# quietly print.
#
# `aggregate_records` is the single derivation both use, so a change log row and
# its verification cannot disagree about what a number means.
ROUND1_RECORDED: dict[str, Any] = {
    "controls_total": 561,
    "offered": 267,
    "abstained": 9,
    "missing": 165,
    "sensitive_skipped": 42,
    "not_fillable": 76,
    "already_filled": 2,
    "form_03_offered": 17,
    "form_03_missing": 7,
    "form_05_controls": 30,
    "form_05_offered": 17,
    "form_05_not_fillable": 4,
    "lc_form_01_offered": 9,
    "lc_form_01_abstained": 7,
    "name_2_decision": "offered",
    "email_readonly_decision": "offered",
}

#: What round 2 left behind - this script's own output before round 3 touched
#: anything, snapshotted as `report_before_round3.md` (+ `runs_before_round3.jsonl`).
ROUND2_RECORDED: dict[str, Any] = {
    "controls_total": 561,
    "offered": 263,
    "abstained": 9,
    "missing": 167,
    "sensitive_skipped": 42,
    "not_fillable": 78,
    "already_filled": 2,
    "form_03_offered": 16,
    "form_03_missing": 8,
    "form_05_controls": 30,
    "form_05_offered": 16,
    "form_05_not_fillable": 5,
    "lc_form_01_offered": 9,
    "lc_form_01_abstained": 7,
    "name_2_decision": "missing",
    "email_readonly_decision": "not_fillable",
}

#: What round 3's three fixes must produce. Stated once, so the change log, the
#: per-form expectations and the section 1 headline cannot drift apart. Anything
#: that is not in this table did not move.
#:
#: The arithmetic, because each line is a prediction rather than an observation:
#:   * finding 7a moves four fact-shaped sub-fields (Company name, Job title, Internship
#:     period, Project name) out of the tailored categories. All four are
#:     `abstained` in exactly one run - L-C form_01 x cross-domain - so that run
#:     gains 4 `offered` and loses 4 `abstained`.
#:   * finding 7b changes no decision at all: a fact-shaped field with no fact was
#:     already `missing`, and the fix only changes the *reason* it reports and the
#:     components it claims to have measured.
#:   * section 6 (`disabled`) adds one control to form_05, which appears in 2 runs.
#:     The control is refused, so it adds 2 to the field total and 2 to
#:     `not_fillable` - and 0 to `offered`, which is why the eligible denominator
#:     (439) does not move.
ROUND3_EXPECTED: dict[str, Any] = {
    "controls_total": 563,
    "offered": 267,
    "abstained": 5,
    "missing": 167,
    "sensitive_skipped": 42,
    "not_fillable": 80,
    "already_filled": 2,
    "form_03_offered": 16,
    "form_03_missing": 8,
    "form_05_controls": 31,
    "form_05_offered": 16,
    "form_05_not_fillable": 6,
    "lc_form_01_offered": 13,
    "lc_form_01_abstained": 3,
    "name_2_decision": "missing",
    "email_readonly_decision": "not_fillable",
    "email_disabled_decision": "not_fillable",
}

#: The run the section 5 row 4 finding (7a) is measured on. Named once because three
#: places quote its counts (the change log, the section 2.2 reading and the
#: finding itself) and a typo would silently produce a report about nothing.
LC_CROSS_DOMAIN_RUN = "fm-L-C-form_01_baseline-cross_domain_profile-jd_cross_domain"

#: Report section 8, as (metric, key, why-it-moved). One table, three data columns
#: taken from `ROUND1_RECORDED` / `ROUND2_RECORDED` / `ROUND3_EXPECTED`, so the three
#: columns cannot be produced by three different lookups that disagree about what a
#: metric means. `main` asserts every key here has a round-3 value, so a row cannot
#: silently lose its after-column and print `absent` where a number belongs.
#:
#: `email_disabled_decision` is deliberately in the table even though the control
#: did not exist in rounds 1 and 2: "absent -> absent -> not_fillable" is the honest
#: record of a control this round added, and dropping the row would hide the fact
#: that the field total grew.
CHANGE_ROWS: list[tuple[str, str, str]] = [
    (
        "whole matrix `controls_total`",
        "controls_total",
        "+2: the `disabled` input added to `form_05_traps` (section 5 row 3), which appears in two runs",
    ),
    (
        "whole matrix `offered`",
        "offered",
        "round 2 lost 4 to two refusals (section 5 rows 1 and 2); round 3 regained 4 from the experience / project fact split (row 4, finding 7a)",
    ),
    (
        "whole matrix `abstained`",
        "abstained",
        "round 3 only: four fact-shaped sub-fields leave the tailored categories and stop being withheld (row 4, finding 7a)",
    ),
    (
        "whole matrix `missing`",
        "missing",
        "round 2: the employer misclassification, 2 runs (section 5 row 1); round 3 moved nothing in or out",
    ),
    (
        "whole matrix `not_fillable`",
        "not_fillable",
        "round 2: `email_readonly`, 2 runs (row 2); round 3: `email_disabled`, 2 runs (row 3)",
    ),
    (
        "whole matrix `sensitive_skipped`",
        "sensitive_skipped",
        "unchanged in all three columns: no identity control was added or removed",
    ),
    (
        "whole matrix `already_filled`",
        "already_filled",
        "unchanged in all three columns: the page-side pre-fill is untouched",
    ),
    (
        "`form_03_help_text` `offered`",
        "form_03_offered",
        "round 2: the employer control is refused instead of answered with the candidate's name (row 1)",
    ),
    (
        "`form_03_help_text` `missing`",
        "form_03_missing",
        "the same control; `missing` is the only bucket an `offered` loss can land in",
    ),
    (
        "`form_05_traps` `controls_total`",
        "form_05_controls",
        "round 3: the `disabled` control is added to the page",
    ),
    (
        "`form_05_traps` `offered`",
        "form_05_offered",
        "round 2: the `readonly` control is refused (row 2)",
    ),
    (
        "`form_05_traps` `not_fillable`",
        "form_05_not_fillable",
        "round 2: `readonly` (row 2); round 3: `disabled` (row 3)",
    ),
    (
        "`form_01_baseline` x `cross_domain_profile` `offered` (L-C)",
        "lc_form_01_offered",
        "round 3: the four fact-shaped sub-fields are offered as facts instead of withheld as tailored (row 4, finding 7a)",
    ),
    (
        "`form_01_baseline` x `cross_domain_profile` `abstained` (L-C)",
        "lc_form_01_abstained",
        "the same four fields (row 4, finding 7a)",
    ),
    (
        "`name_2` decision",
        "name_2_decision",
        "round 2, and unchanged since: `offered` -> `missing` (row 1)",
    ),
    (
        "`email_readonly` decision",
        "email_readonly_decision",
        "round 2, and unchanged since: `offered` -> `not_fillable` (row 2)",
    ),
    (
        "`email_disabled` decision",
        "email_disabled_decision",
        "round 3: the control did not exist before this round (row 3)",
    ),
]

# --------------------------------------------------------------------------- #
# Mirror of extension/src/content.ts
# --------------------------------------------------------------------------- #

SELECTOR = 'input, textarea, select, [contenteditable="true"], [contenteditable=""], [role="textbox"]'
MAX_FIELDS = 400
MAX_HELP_CHARS = 180
MAX_OPTIONS = 40
MAX_LABEL_CHARS = 200
LABEL_ANCESTOR_DEPTH = 4
#: Type-based refusals to read a value. The attribute-based pair (`readonly`,
#: `disabled`) are predicates below and join this condition in `extract_fields`.
NEVER_READ_TYPES = {"password", "file"}

#: Elements whose text is *section* level and may never name a field
#: (`content.ts:isSectionLevelText`). Round 2, report section 5 row 1.
SECTION_LEVEL_TAGS = frozenset({"legend", "caption", "h1", "h2", "h3", "h4", "h5", "h6"})

#: Control types the server refuses to write to (`server/field_map.SKIPPED_TYPES`).
SKIP_TYPES = {"hidden", "submit", "button", "reset", "image", "file", "password"}

#: The six mutually exclusive states this script classifies each field into.
DECISIONS = ("offered", "abstained", "missing", "sensitive_skipped", "not_fillable", "already_filled")

FORM_DIMENSIONS = {
    "form_01_baseline": "baseline (reference shape)",
    "form_02_naming": "field naming style + label source",
    "form_03_help_text": "help text in <legend> + legend-only field names",
    "form_04_maxlength": "maxlength tiers 50 / 300 / 1000",
    "form_05_traps": "trap controls + page-side pre-fill",
    "form_06_bilingual": "bilingual labels + Chinese-only labels + contenteditable",
}

RESUME_ORDER = [
    "full_profile",
    "sparse_profile",
    "cross_domain_profile",
    "long_prose_profile",
    "minimal_profile",
]
FORM_ORDER = [
    "form_01_baseline",
    "form_02_naming",
    "form_03_help_text",
    "form_04_maxlength",
    "form_05_traps",
    "form_06_bilingual",
]
JD_ORDER = ["jd_named", "jd_implied", "jd_cross_domain"]


# --------------------------------------------------------------------------- #
# Check harness
# --------------------------------------------------------------------------- #


class Report:
    def __init__(self, verbose: bool = False) -> None:
        self.verbose = verbose
        self.passed = 0
        self.failures: list[str] = []

    def check(self, ok: bool, label: str, detail: str = "") -> bool:
        if ok:
            self.passed += 1
            if self.verbose:
                print(f"  PASS  {label}")
            return True
        self.failures.append(f"{label}{' - ' + detail if detail else ''}")
        print(f"  FAIL  {label}{' - ' + detail if detail else ''}")
        return False

    def equal(self, actual: Any, expected: Any, label: str) -> bool:
        return self.check(actual == expected, label, f"expected {expected!r}, got {actual!r}")

    def section(self, title: str) -> None:
        print(f"\n{title}")
        print("-" * len(title))


# --------------------------------------------------------------------------- #
# Data
# --------------------------------------------------------------------------- #


@dataclass
class Resume:
    resume_id: str
    path: Path
    data: dict[str, Any]

    @property
    def profile(self) -> dict[str, Any]:
        return self.data.get("profile") or {}

    @property
    def authorised_modules(self) -> list[str]:
        return list(self.data.get("authorised_modules") or [])

    @property
    def declared_skills(self) -> list[str]:
        return list(self.data.get("declared_skills") or [])

    @property
    def intentionally_absent(self) -> list[str]:
        return list(self.data.get("intentionally_absent") or [])


@dataclass
class Jd:
    jd_id: str
    path: Path
    data: dict[str, Any]

    @property
    def text(self) -> str:
        return str(self.data.get("text") or "")

    @property
    def expected_skills(self) -> list[str]:
        return list(self.data.get("expected_jd_skills") or [])


@dataclass
class Form:
    form_id: str
    path: Path
    html: str
    fields: list[dict[str, Any]] = dc_field(default_factory=list)


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_resumes() -> list[Resume]:
    return [Resume(p.stem, p, load_json(p)) for p in sorted(RESUME_DIR.glob("*.json"))]


def load_jds() -> list[Jd]:
    return [Jd(p.stem, p, load_json(p)) for p in sorted(JD_DIR.glob("*.json"))]


# --------------------------------------------------------------------------- #
# DOM extraction - mirrors extension/src/content.ts
# --------------------------------------------------------------------------- #


def _text_of(node: Any) -> str:
    if node is None:
        return ""
    return re.sub(r"\s+", " ", node.get_text(" ") or "").strip()


def _is_fillable_control(el: Any) -> bool:
    """Mirror of `content.ts:isFillableControl`."""
    if el.has_attr("hidden"):
        return False
    if el.get("aria-hidden") == "true":
        return False
    if el.name == "input" and (el.get("type") or "text").lower() == "hidden":
        return False
    return True


def _is_content_editable(el: Any) -> bool:
    tag = el.name.lower()
    if el.get("contenteditable") in ("true", ""):
        return True
    return el.get("role") == "textbox" and tag not in ("input", "textarea")


def _is_section_level(el: Any) -> bool:
    """Mirror of `content.ts:isSectionLevelText`. Round 2, report section 5 row 1."""
    if (el.name or "").lower() in SECTION_LEVEL_TAGS:
        return True
    return el.get("role") == "heading"


def _is_readonly_control(el: Any) -> bool:
    """Mirror of `content.ts:isReadonlyControl`. `readonly` is an attribute."""
    if (el.name or "").lower() not in ("input", "textarea"):
        return False
    return el.has_attr("readonly")


def _is_disabled_control(el: Any) -> bool:
    """Mirror of `content.ts:isDisabledControl`. Round 3, report section 6.

    Same family as `readonly`, one tag wider: `disabled` is valid on a `<select>`
    as well as on a text control.
    """
    if (el.name or "").lower() not in ("input", "textarea", "select"):
        return False
    return el.has_attr("disabled")


def _resolve_section_context(soup: Any, el: Any) -> str:
    """Mirror of `content.ts:resolveSectionContext`. Context, never a name."""
    fieldset = el.find_parent("fieldset")
    if fieldset is not None:
        text = _text_of(fieldset.find("legend"))
        if text:
            return text[:MAX_LABEL_CHARS]
    node = el.parent
    for _depth in range(LABEL_ANCESTOR_DEPTH):
        if node is None:
            break
        sibling = node.find_previous_sibling()
        while sibling is not None:
            if _is_section_level(sibling):
                text = _text_of(sibling)
                if text:
                    return text[:MAX_LABEL_CHARS]
            sibling = sibling.find_previous_sibling()
        node = node.parent
    return ""


def _resolve_label(soup: Any, el: Any) -> str:
    """Mirror of `content.ts:resolveLabel`, in the same order."""
    el_id = el.get("id")
    if el_id:
        explicit = soup.find("label", attrs={"for": el_id})
        text = _text_of(explicit)
        if text:
            return text[:MAX_LABEL_CHARS]
    aria = (el.get("aria-label") or "").strip()
    if aria:
        return aria[:MAX_LABEL_CHARS]
    labelled_by = el.get("aria-labelledby")
    if labelled_by:
        parts = [
            _text_of(soup.find(id=token))
            for token in labelled_by.split()
        ]
        parts = [p for p in parts if p]
        if parts:
            return " ".join(parts)[:MAX_LABEL_CHARS]
    wrapping = el.find_parent("label")
    if wrapping is not None:
        clone = _clone_without_controls(soup, wrapping)
        text = _text_of(clone)
        if text:
            return text[:MAX_LABEL_CHARS]
    # Nearby text: only a LEAF element counts, walking outwards. See the comment
    # in content.ts - a container with element children is a block of the form,
    # not the name of one field.
    node = el
    for _depth in range(LABEL_ANCESTOR_DEPTH):
        if node is None:
            break
        sibling = node.find_previous_sibling()
        while sibling is not None:
            # Section-level text is context, not a name. Round 2, report 5 row 1.
            if len(sibling.find_all(recursive=False)) == 0 and not _is_section_level(sibling):
                text = _text_of(sibling)
                if text and len(text) <= MAX_LABEL_CHARS:
                    return text
            sibling = sibling.find_previous_sibling()
        node = node.parent
    return ""


def _clone_without_controls(soup: Any, node: Any) -> Any:
    """Copy of `node` with input/select/textarea/button removed (content.ts:132)."""
    from bs4 import BeautifulSoup

    clone = BeautifulSoup(str(node), "html.parser")
    root = clone.find(node.name)
    if root is None:
        return clone
    for child in root.find_all(["input", "select", "textarea", "button"]):
        child.decompose()
    return root


def _resolve_help_text(soup: Any, el: Any) -> str:
    """Mirror of `content.ts:resolveHelpText`.

    The `<legend>` exclusion is the point of this function: a section heading is
    not a field's help text, and letting it through made a "Why do you want this
    role?" field inherit the word "skills" from its section heading.
    """
    described_by = el.get("aria-describedby")
    if described_by:
        parts = [_text_of(soup.find(id=token)) for token in described_by.split()]
        parts = [p for p in parts if p]
        if parts:
            return " ".join(parts)[:MAX_HELP_CHARS]
    title = (el.get("title") or "").strip()
    if title:
        return title[:MAX_HELP_CHARS]
    nxt = el.find_next_sibling()
    if nxt is not None and nxt.name not in {"input", "select", "textarea", "button"}:
        text = _text_of(nxt)
        if text and len(text) <= MAX_HELP_CHARS:
            return text
    return ""


def _resolve_options(soup: Any, el: Any) -> list[str]:
    if el.name == "select":
        texts = [_text_of(option) for option in el.find_all("option")]
        return [t for t in texts if t][:MAX_OPTIONS]
    kind = (el.get("type") or "").lower()
    if el.name == "input" and kind in {"radio", "checkbox"}:
        name = el.get("name")
        if not name:
            own = _resolve_label(soup, el)
            return [own] if own else []
        group = soup.find_all("input", attrs={"type": kind, "name": name})
        out = [(_resolve_label(soup, item) or (item.get("value") or "")) for item in group]
        return [o for o in out if o][:MAX_OPTIONS]
    return []


def _current_value(el: Any) -> str:
    tag = el.name.lower()
    if tag in {"select", "textarea"}:
        if tag == "select":
            selected = el.find("option", selected=True)
            return _text_of(selected) if selected is not None else ""
        return el.get_text() or ""
    if tag == "input":
        kind = (el.get("type") or "text").lower()
        if kind in {"radio", "checkbox"}:
            return (el.get("value") or "checked") if el.has_attr("checked") else ""
        return el.get("value") or ""
    return el.get_text() or ""


def _build_selector(soup: Any, el: Any) -> str:
    el_id = el.get("id")
    if el_id and not re.match(r"^\d", el_id):
        if len(soup.find_all(id=el_id)) == 1:
            return f"#{el_id}"
    name = el.get("name")
    if name:
        if len(soup.find_all(el.name, attrs={"name": name})) == 1:
            return f'{el.name}[name="{name}"]'
    return el.name


def extract_fields(html: str) -> list[dict[str, Any]]:
    """Approximate `content.ts:scanPage`.

    `field_id` is deliberately left out of the payload: the server recomputes it
    from the same four attributes when it is absent, and sending it from here
    would add a second implementation of the fingerprint. That the content
    script's own ids agree with this server's is checked by
    `extension/scripts/browser_check.mjs`, not here.
    """
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    out: list[dict[str, Any]] = []
    seen: set[int] = set()

    for el in soup.select(SELECTOR):
        if id(el) in seen:
            continue
        seen.add(id(el))
        if len(out) >= MAX_FIELDS:
            break
        if not _is_fillable_control(el):
            continue

        tag = el.name.lower()
        content_editable = _is_content_editable(el)
        control_type = "text" if content_editable else (el.get("type") or "text").lower()

        max_length = None
        raw_max = el.get("maxlength")
        if raw_max and str(raw_max).strip().isdigit():
            max_length = int(str(raw_max).strip())

        out.append(
            {
                "tag": "contenteditable" if content_editable else tag,
                "type": control_type,
                "name": el.get("name") or "",
                "id": el.get("id") or "",
                "label": _resolve_label(soup, el),
                "placeholder": el.get("placeholder") or "",
                "aria_label": el.get("aria-label") or "",
                "required": el.has_attr("required") or el.get("aria-required") == "true",
                "max_length": max_length,
                "options": _resolve_options(soup, el),
                "help_text": _resolve_help_text(soup, el),
                # Three reasons a value is never read: it is a secret by type
                # (password / file), the page locked the control, or the page
                # switched it off. The control is reported either way; only the
                # value is withheld.
                "current_value": ""
                if control_type in NEVER_READ_TYPES
                or _is_readonly_control(el)
                or _is_disabled_control(el)
                else _current_value(el)[:2000],
                "selector": _build_selector(soup, el),
                "readonly": _is_readonly_control(el),
                "disabled": _is_disabled_control(el),
                "section_context": _resolve_section_context(soup, el),
            }
        )
    return out


# --------------------------------------------------------------------------- #
# Static file server with an access log (H2: nothing may ever POST)
# --------------------------------------------------------------------------- #


class _RecordingHandler(SimpleHTTPRequestHandler):
    server_version = "FormMatrixStatic/1.0"

    def log_message(self, fmt: str, *args: Any) -> None:  # noqa: A003
        return  # silence stderr; log_request records what we need

    def log_request(self, code: Any = "-", size: Any = "-") -> None:
        try:
            status = int(code)
        except (TypeError, ValueError):
            status = 0
        self.server.access_log.append(  # type: ignore[attr-defined]
            {"method": self.command, "path": self.path, "status": status}
        )


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def start_static_server(port: int) -> ThreadingHTTPServer:
    handler = functools.partial(_RecordingHandler, directory=str(FORM_DIR))
    httpd = ThreadingHTTPServer(("127.0.0.1", port), handler)
    httpd.access_log = []  # type: ignore[attr-defined]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


# --------------------------------------------------------------------------- #
# Backend
# --------------------------------------------------------------------------- #


def start_backend(port: int, kb_provider: Any) -> Any:
    import uvicorn

    from server.app import create_app

    app = create_app(require_token=True, token=TOKEN, kb_provider=kb_provider)
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", lifespan="on")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    deadline = time.time() + 60
    while time.time() < deadline:
        if getattr(server, "started", False):
            return server
        if not thread.is_alive():
            raise RuntimeError("the backend thread died before it started")
        time.sleep(0.05)
    raise RuntimeError("the backend did not start within 60s")


# --------------------------------------------------------------------------- #
# Run plan
# --------------------------------------------------------------------------- #


@dataclass
class RunSpec:
    layer: str
    form_id: str
    resume_id: str
    jd_id: str
    repeat: int = 1

    @property
    def run_id(self) -> str:
        suffix = f"-r{self.repeat}" if self.repeat > 1 else ""
        return f"fm-{self.layer}-{self.form_id}-{self.resume_id}-{self.jd_id}{suffix}"


def build_run_plan() -> list[RunSpec]:
    plan: list[RunSpec] = []
    # L-A: single-variable sweep across form shape, everything else held.
    for form_id in FORM_ORDER:
        plan.append(RunSpec("L-A", form_id, "full_profile", "jd_named"))
    # L-B: single-variable sweep across profile.
    for resume_id in RESUME_ORDER:
        plan.append(RunSpec("L-B", "form_01_baseline", resume_id, "jd_named"))
    # L-C: cross combinations chosen to reach states L-A and L-B cannot.
    plan.extend(
        [
            RunSpec("L-C", "form_01_baseline", "cross_domain_profile", "jd_cross_domain"),
            RunSpec("L-C", "form_06_bilingual", "cross_domain_profile", "jd_named"),
            RunSpec("L-C", "form_05_traps", "sparse_profile", "jd_implied"),
            RunSpec("L-C", "form_04_maxlength", "long_prose_profile", "jd_named"),
            RunSpec("L-C", "form_03_help_text", "minimal_profile", "jd_implied"),
        ]
    )
    # L-D: repeatability. Same cell three times, offline and deterministic.
    for index in (1, 2, 3):
        plan.append(RunSpec("L-D", "form_02_naming", "full_profile", "jd_named", repeat=index))
    return plan


# --------------------------------------------------------------------------- #
# Recording
# --------------------------------------------------------------------------- #


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


MESSAGE_KINDS: tuple[tuple[str, str], ...] = (
    ("extremely sensitive", "sensitive"),
    ("already entered something", "already_filled"),
    ("withheld rather than guessed", "abstained"),
    ("not one of this control's options", "option_mismatch"),
    ("cannot be expressed in", "length_unanswerable"),
    ("shortened to fit", "trimmed"),
    ("so your profile's own wording was used instead", "draft_replaced"),
    ("was not supported", "unsupported_claim"),
    ("offline stub: copied verbatim", "copied_from_profile"),
    ("offline stub: no deterministic value", "stub_no_value"),
    ("no information for this field", "no_fact"),
    ("nothing in your authorised profile answers", "no_fact"),
    ("no fact in the authorised profile", "no_fact"),
    ("hidden input", "not_fillable"),
    ("submit control", "not_fillable"),
    ("button control", "not_fillable"),
    ("reset control", "not_fillable"),
    ("image submit control", "not_fillable"),
    ("file upload", "not_fillable"),
    ("password field", "not_fillable"),
    ("readonly control", "not_fillable"),
    ("disabled control", "not_fillable"),
    ("unsupported control", "not_fillable"),
)


def message_kinds(message: str) -> list[str]:
    low = (message or "").lower()
    return [kind for needle, kind in MESSAGE_KINDS if needle in low]


def classify_decision(row: dict[str, Any]) -> str:
    """The exclusive six-way state for one field.

    Precedence, stated because it is a choice: not-fillable first (we never touch
    it), then sensitive (a hard rule), then a value, then abstained, then missing,
    then already-filled.

    The server's own `already_filled` count is deliberately NOT exclusive - its
    docstring says so - because a sensitive control that already holds a value is
    counted in both. Classifying by precedence is what makes the six add up; the
    overlap is reconciled separately rather than hidden.
    """
    if not row.get("fillable", True):
        return "not_fillable"
    if row.get("sensitive_skipped"):
        return "sensitive_skipped"
    if row.get("suggested_value") is not None:
        return "offered"
    if row.get("abstained"):
        return "abstained"
    if row.get("missing"):
        return "missing"
    if row.get("already_filled"):
        return "already_filled"
    return "unclassified"


def build_record(
    spec: RunSpec,
    *,
    form: Form,
    scanned: dict[str, Any],
    generated: dict[str, Any],
    page_url: str,
    canary: str,
    declared_skills: set[str],
    jd_text: str,
) -> dict[str, Any]:
    from src.taxonomy import canonicalise, match_skills

    rows = generated["fields"]
    scan_rows = {row["field_id"]: row for row in scanned["fields"]}

    per_field: list[dict[str, Any]] = []
    for row in rows:
        value = row.get("suggested_value")
        decision = classify_decision(row)
        source_row = scan_rows.get(row["field_id"], {})
        per_field.append(
            {
                "field_id": row["field_id"],
                "label": row.get("label") or "",
                "name": source_row.get("name") or "",
                "element_id": source_row.get("id") or "",
                "type": row.get("type") or "",
                "tag": row.get("tag") or "",
                "required": bool(row.get("required")),
                "max_length": row.get("max_length"),
                "decision": decision,
                "abstained": bool(row.get("abstained")),
                "missing": bool(row.get("missing")),
                "sensitive": bool(source_row.get("sensitive")),
                "fillable": bool(row.get("fillable", True)),
                "already_filled": bool(row.get("already_filled")),
                # H3: a hash and a length, never the value.
                "value_hash": _sha(value) if value else "",
                "value_length": len(value) if value else 0,
                "confidence": round(float(row.get("confidence") or 0.0), 4),
                "components_present": list(row.get("components_present") or []),
                "source": row.get("source") or "",
                # The classification, so section 1 can say which *kinds* of field
                # are withheld rather than only how many. It is a *scan*-side
                # fact - `FieldSuggestion` has no `category` key, only
                # `NormalizedField` does - so it is read from the scan row, the
                # same one `name` / `id` / `sensitive` / `options` come from.
                "category": source_row.get("category") or "",
                "jd_relevance": (row.get("jd_relevance") or "")[:60],
                "needs_user_confirmation": bool(row.get("needs_user_confirmation")),
                "message_kinds": message_kinds(row.get("message") or ""),
                "has_message": bool((row.get("message") or "").strip()),
                "reasons": list(row.get("reasons") or [])[:4],
                "options_offered": list(source_row.get("options") or [])[:8],
            }
        )

    derived = {key: 0 for key in DECISIONS}
    for row in per_field:
        derived[row["decision"]] = derived.get(row["decision"], 0) + 1
    unclassified = derived.pop("unclassified", 0)

    counts = generated.get("counts") or {}
    overlap = sum(
        1 for row in per_field if row["sensitive"] and row["already_filled"]
    )

    offered_values = [
        row["suggested_value"]
        for row in rows
        if row.get("suggested_value") is not None
    ]
    fabricated = sorted(
        {canonicalise(s) for s in match_skills(" ".join(offered_values))} - declared_skills
    )

    response_text = json.dumps(generated, ensure_ascii=False)
    return {
        "run_id": spec.run_id,
        "layer": spec.layer,
        "form_id": spec.form_id,
        "resume_id": spec.resume_id,
        "jd_id": spec.jd_id,
        "repeat": spec.repeat,
        "mode": generated.get("mode") or "",
        "condition": generated.get("condition") or "",
        "server_run_id": generated.get("run_id") or "",
        "page_url": page_url,
        "page_source": "127.0.0.1 static server over demo/form_matrix/",
        "retrieval_active": not any(
            "retrieval unavailable" in note for note in (generated.get("notes") or [])
        ),
        "scan_counts": scanned.get("counts") or {},
        "per_field": per_field,
        "counts": derived,
        "counts_server": {
            "offered": counts.get("suggestion_offered", 0),
            "abstained": counts.get("withheld_low_confidence", 0),
            "missing": counts.get("missing", 0),
            "sensitive_skipped": counts.get("sensitive_skipped", 0),
            "not_fillable": counts.get("not_fillable", 0),
            "already_filled": counts.get("already_filled", 0),
        },
        "counts_reconciliation": {
            "fields_total": len(per_field),
            "derived_sum": sum(derived.values()),
            "unclassified": unclassified,
            "sensitive_and_already_filled_overlap": overlap,
        },
        "invariants": {
            # H2. `submit_clicked` is False by three independent arguments, all
            # checked elsewhere in this script: no value is ever offered for a
            # submit-shaped control, the API has no write route, and the static
            # server's access log holds no POST.
            "submit_clicked": False,
            "submit_evidence": "no value offered for any submit-shaped control; no write route in openapi; 0 POSTs in the access log",
            "persisted_text_found": False,  # replaced by the scan result below
            "identity_doc_echoed": canary in response_text,
            "fabricated_claims": fabricated,
            "decision_partition_ok": unclassified == 0 and sum(derived.values()) == len(per_field),
            "no_value_without_a_decision": all(
                (row["value_hash"] != "") == (row["decision"] == "offered")
                for row in per_field
            ),
        },
        "notes": list(generated.get("notes") or []),
        "risk_flag_count": len(generated.get("risk_flags") or []),
        "jd_analysis_counts": {
            "responsibilities": len((generated.get("jd_analysis") or {}).get("responsibilities") or []),
            "requirements": len((generated.get("jd_analysis") or {}).get("requirements") or []),
            "keywords": len((generated.get("jd_analysis") or {}).get("keywords") or []),
            "missing_from_user_profile": len(
                (generated.get("jd_analysis") or {}).get("missing_from_user_profile") or []
            ),
        },
        "jd_text_len": len(jd_text),
    }


# --------------------------------------------------------------------------- #
# Privacy scanning (H3)
# --------------------------------------------------------------------------- #


def build_sentinels(resumes: list[Resume], jds: list[Jd]) -> list[str]:
    """Distinctive source strings that must never appear in an artifact.

    Rule, stated so it can be argued with: a candidate sentinel is at least 8
    characters AND contains either a space or a non-alphanumeric character. That
    keeps multi-word names, addresses (which carry `@` or `.`) and long prose
    fragments, and drops bare single tokens such as a city name or a canonical
    skill word. Those single tokens are public vocabulary; their appearance in a
    log is not a disclosure of the applicant's own text. Everything that would
    identify the applicant or quote their posting is caught.
    """
    out: set[str] = set()

    def add(value: Any) -> None:
        if not isinstance(value, str):
            return
        text = value.strip()
        if len(text) < 8:
            return
        if " " not in text and not re.search(r"[^A-Za-z0-9]", text):
            return
        out.add(text)

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if key in {"resume_id", "jd_id", "title", "purpose", "notes"}:
                    continue
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)
        else:
            add(node)

    for resume in resumes:
        walk(resume.profile)
        for skill in resume.declared_skills:
            if " " in skill:
                add(skill)
    for jd in jds:
        for line in jd.text.splitlines():
            stripped = line.strip(" -*\t")
            if len(stripped) >= 12 and " " in stripped:
                out.add(stripped)
    return sorted(out)


def redact(text: str, sentinels: list[str]) -> str:
    for needle in sentinels:
        if needle in text:
            text = text.replace(needle, "[redacted]")
    return text


def scan_for_sentinels(paths: list[Path], sentinels: list[str]) -> dict[str, Any]:
    hits: list[dict[str, str]] = []
    scanned = 0
    for path in paths:
        if not path.exists() or not path.is_file():
            continue
        scanned += 1
        try:
            blob = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for needle in sentinels:
            if needle in blob:
                hits.append({"file": str(path.relative_to(REPO_ROOT)), "sha256_8": _sha(needle)[:8]})
    return {"files_scanned": scanned, "hits": hits, "sentinels": len(sentinels)}


def scan_directory_for_sentinels(root: Path, sentinels: list[str]) -> dict[str, Any]:
    files = [p for p in root.rglob("*") if p.is_file()] if root.exists() else []
    return scan_for_sentinels(files, sentinels)


def aggregate_records(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Derive one change-log column from a run file.

    Used twice: once on this run's records, and once on a snapshot of an earlier
    round, so the recorded "before" columns of report section 8 are *checked*
    against the records rather than trusted as a transcription. Also used on the
    round-1 and round-2 snapshots, which is why every `row[...]` is a `.get`.
    """
    fields = [row for rec in records for row in rec["per_field"]]
    out: dict[str, Any] = {
        key: sum(1 for row in fields if row["decision"] == key) for key in DECISIONS
    }
    out["controls_total"] = len(fields)

    def form_counts(form_id: str, layer: str) -> dict[str, int]:
        rows = [
            row
            for rec in records
            if rec["form_id"] == form_id and rec["layer"] == layer
            for row in rec["per_field"]
        ]
        counts = {key: sum(1 for row in rows if row["decision"] == key) for key in DECISIONS}
        counts["controls_total"] = len(rows)
        return counts

    def decision_by_name(form_id: str, name: str) -> str:
        seen = sorted(
            {
                row["decision"]
                for rec in records
                if rec["form_id"] == form_id
                for row in rec["per_field"]
                if row.get("name") == name
            }
        )
        return ",".join(seen) or "absent"

    la03 = form_counts("form_03_help_text", "L-A")
    la05 = form_counts("form_05_traps", "L-A")
    lc01 = next((rec for rec in records if rec["run_id"] == LC_CROSS_DOMAIN_RUN), None)
    out["form_03_offered"] = la03["offered"]
    out["form_03_missing"] = la03["missing"]
    out["form_05_controls"] = la05["controls_total"]
    out["form_05_offered"] = la05["offered"]
    out["form_05_not_fillable"] = la05["not_fillable"]
    out["lc_form_01_offered"] = lc01["counts"]["offered"] if lc01 else "n/a"
    out["lc_form_01_abstained"] = lc01["counts"]["abstained"] if lc01 else "n/a"
    out["name_2_decision"] = decision_by_name("form_03_help_text", "name_2")
    out["email_readonly_decision"] = decision_by_name("form_05_traps", "email_readonly")
    out["email_disabled_decision"] = decision_by_name("form_05_traps", "email_disabled")
    return out


def read_snapshot(path: Path) -> list[dict[str, Any]] | None:
    """Load a previous round's `runs.jsonl`, or None when it is not on disk."""
    if not path.exists():
        return None
    try:
        return [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    except (json.JSONDecodeError, OSError):
        return None


# --------------------------------------------------------------------------- #
# H7 - which files decide policy, and have they moved
# --------------------------------------------------------------------------- #

POLICY_FILES = [
    "config.yaml",
    "src/pipeline/confidence.py",
    "src/rules/fields.py",
    "src/taxonomy.py",
    "src/retrieval/store.py",
    "src/llm/extractor.py",
    "src/llm/offline.py",
    "src/sanitize.py",
    "server/field_map.py",
    "server/services.py",
    "server/schemas.py",
    # Round 2 (R6). The page-side extraction rules decide what this matrix is even
    # able to see, so they are fingerprinted alongside the server's policy. This
    # file changed twice this round - M1 (section text may not name a field) and
    # M2 (readonly) - which is exactly why it is listed.
    "extension/src/content.ts",
]


def source_fingerprint() -> dict[str, Any]:
    from src import config as src_config
    from src.config import ConfidenceConfig

    files = {}
    for rel in POLICY_FILES:
        path = REPO_ROOT / rel
        files[rel] = (
            hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else "MISSING"
        )
    confidence = ConfidenceConfig.load()
    return {
        "note": (
            "Recorded so a later run can prove the abstention / similarity policy was not "
            "edited to make this matrix pass. This is a hash of the files, not a git commit: "
            "the repository is not a git working tree."
        ),
        "files": files,
        "abstention_threshold": confidence.threshold,
        "weights": {
            "retrieval": confidence.w_retrieval,
            "llm_self": confidence.w_llm_self,
        },
        "abstain_on_either_component": bool(confidence.abstain_on_either),
        "similarity_floor": src_config.get("retrieval", "similarity_floor"),
        "similarity_ceiling": src_config.get("retrieval", "similarity_ceiling"),
        "embedding_backend": src_config.get("retrieval", "embedding_backend"),
        "corpus_recalibrated_for_this_matrix": False,
        "corpus_note": (
            "The knowledge base was NOT rebuilt and no recalibration was run, so the "
            "similarity scale is the one already documented for the same 54-chunk corpus "
            "(floor 0.3663, ceiling 0.5633). scripts/calibrate_similarity.py was not invoked."
        ),
    }


# --------------------------------------------------------------------------- #
# Report rendering
# --------------------------------------------------------------------------- #


def _pct(part: int, whole: int) -> str:
    return f"{100.0 * part / whole:.1f}%" if whole else "n/a"


def render_report(
    *,
    records: list[dict[str, Any]],
    resumes: dict[str, Resume],
    forms: dict[str, Form],
    checks: dict[str, Any],
    l2_text: str,
    h3: dict[str, Any],
    fingerprint: dict[str, Any],
    findings: list[dict[str, Any]],
    total_checks: int,
    change_log: dict[str, Any],
    abstention: dict[str, Any],
    profile_missing: list[int],
    live: dict[str, Any] | None = None,
) -> str:
    lines: list[str] = []
    add = lines.append

    all_fields = [row for rec in records for row in rec["per_field"]]
    field_total = len(all_fields)
    per_decision = {key: sum(1 for row in all_fields if row["decision"] == key) for key in DECISIONS}
    runs_with = {
        key: sum(1 for rec in records if rec["counts"].get(key)) for key in DECISIONS
    }
    fabricated_total = sum(len(rec["invariants"]["fabricated_claims"]) for rec in records)
    runs_total = len(records)

    # --- round 2: the numbers section 1 leads with, and the form-to-form movement
    # section 2.1 has to explain. All recomputed from `records`; none hard-coded.
    sensitive_blocked = per_decision["sensitive_skipped"]
    not_eligible = (
        per_decision["not_fillable"] + per_decision["already_filled"] + sensitive_blocked
    )
    eligible = field_total - not_eligible
    la_by_form: dict[str, dict[str, int]] = {}
    for form_id in FORM_ORDER:
        la_rows = [
            row
            for rec in records
            if rec["layer"] == "L-A" and rec["form_id"] == form_id
            for row in rec["per_field"]
        ]
        la_by_form[form_id] = {
            key: sum(1 for row in la_rows if row["decision"] == key) for key in DECISIONS
        }
    baseline_counts = la_by_form.get("form_01_baseline", {})
    movements = [
        f"`{form_id}` {key} {la_by_form[form_id][key] - baseline_counts.get(key, 0):+d}"
        for form_id in FORM_ORDER
        if form_id != "form_01_baseline"
        for key in DECISIONS
        if la_by_form[form_id][key] != baseline_counts.get(key, 0)
    ]
    severity_rank = {"high": 0, "medium": 1, "low": 2}
    ordered_findings = sorted(
        findings,
        key=lambda item: (
            severity_rank.get(str(item.get("severity", "low")), 3),
            int(item.get("order", 99)),
        ),
    )

    add("# Form matrix - browser assistant under field and profile diversity")
    add("")
    add(f"Driver: `scripts/run_form_matrix.py`. Runs: **{runs_total}**. Controls seen: **{field_total}**.")
    add(f"Condition: **{CONDITION}** (retrieval + model). Server mode: **offline_stub** for every run.")
    add("")
    add("Scope, stated first: this matrix drives the assistant's own HTTP contract")
    add("(`/scan` then `/generate`) with the content script's DOM extraction mirrored in")
    add("Python. It is not a browser run. Answer quality is not measurable here, because")
    add("the offline stub is a literal extractor, not a model.")
    add("")

    # ---------------------------------------------------------------- 1. headline
    add("## 1. Headline (counts)")
    add("")
    add(
        "**Mode: offline_stub - quality claims (fabrication, abstention quality, answer "
        "quality) do not apply to this matrix. See section 6.**"
    )
    add("")
    add(
        f"Total controls: **{field_total}**. Three groups are not candidates for a value at all: "
        f"`not_fillable` {per_decision['not_fillable']} + `already_filled` "
        f"{per_decision['already_filled']} + `sensitive_skipped` {sensitive_blocked} = "
        f"{not_eligible}. **Controls that could be filled: {eligible}** - and the assistant "
        f"offered **{per_decision['offered']}/{eligible}** of them."
    )
    add("")
    add(
        "**Hard rule: sensitive "
        f"{sensitive_blocked}/{sensitive_blocked} correctly withheld, with no value echoed.**"
    )
    add("")
    add(
        "**Abstention triggered only on the cross-domain profile, only on posting-tailored "
        "fields (skills / experience / project, i.e. `services.TAILORED_CATEGORIES`):** "
        f"{abstention['fields']} field(s) across "
        f"{abstention['runs']} run(s), categories {abstention['categories']}. Zero abstentions "
        "on personal or education facts - the documented design of "
        "`services._evidence_for_field`, and checked against the records rather than asserted "
        "in prose. Round 3 shrank the eligible set: the employer, job title, internship "
        "period and project name are facts about the candidate rather than answers tailored "
        "to the posting, so they left `services.TAILORED_CATEGORIES` and can no longer be "
        "withheld (section 5 row 4)."
    )
    add("")
    add("Decision distribution over every control in every run. Counts are the headline;")
    add("percentages are supplementary. All six states are kept and none is merged. Three")
    add("defects fixed over two rounds moved these numbers - the employer misclassification")
    add("(section 5 row 1), the `readonly` control (row 2), the `disabled` control round 3")
    add("added (row 3) and the experience / project fact split (row 4). The change log in")
    add("section 8 lists every cell they touched, and a metric that is not in that table is")
    add("identical to round 1.")
    add("")
    add("| decision | fields | share | runs containing at least one |")
    add("|---|---:|---:|---:|")
    for key in DECISIONS:
        add(
            f"| `{key}` | {per_decision[key]}/{field_total} | {_pct(per_decision[key], field_total)} "
            f"| {runs_with[key]}/{runs_total} |"
        )
    add("")
    # The six-way split above is this script's derivation, which classifies by
    # precedence. `schemas.GenerateCounts` counts `already_filled` orthogonally,
    # so its own figure is larger and a reader comparing the two would read the
    # difference as a defect. Carried into the report rather than left in the
    # console, where only the person who ran it can see it.
    overlap_runs = sum(
        1
        for rec in records
        if rec["counts_reconciliation"]["sensitive_and_already_filled_overlap"]
    )
    add(
        "Arithmetic note, worth stating because it recurs whenever this table is checked "
        "against the API's own counts: the six buckets are *this script's* derivation, which "
        "classifies each control by precedence. `schemas.GenerateCounts` also counts "
        f"`already_filled` orthogonally, so its own `already_filled` is larger - {overlap_runs} "
        "run(s) hold a control that is both sensitive and already filled, and the server counts "
        "it in both buckets. The per-run reconciliation is asserted in the machine checks. No "
        "number above is the server's raw total, and none is meant to be."
    )
    add("")
    add(
        f"**Fabricated claims: {fabricated_total}.** Structurally trivial in offline mode - the "
        "stub is a literal extractor and cannot invent, so this zero is about wiring, not about "
        "a real model. See sections 6 and 7."
    )
    add("")
    add("| hard constraint | status |")
    add("|---|---|")
    add(f"| H2 no submission | {'PASS' if checks['h2'] else 'FAIL'} - {checks['h2_detail']} |")
    add(f"| H3 no persisted plaintext | {'PASS' if checks['h3'] else 'FAIL'} - {checks['h3_detail']} |")
    add(f"| H5 no document number | {'PASS' if checks['h5'] else 'FAIL'} - {checks['h5_detail']} |")
    add(f"| H6 missing means null | {'PASS' if checks['h6'] else 'FAIL'} - {checks['h6_detail']} |")
    add("")
    add("Machine checks: " + checks["machine_summary"] + ".")
    add("")

    # ------------------------------------------------------------- 2. dimensions
    add("## 2. Which dimension moves which decision")
    add("")
    add("### 2.1 Form shape (L-A: 6 forms x full_profile x jd_named, everything else held)")
    add("")
    add("| form | dimension under test | controls | offered | abstained | missing | sensitive | not_fillable | already_filled |")
    add("|---|---|---:|---:|---:|---:|---:|---:|---:|")
    for form_id in FORM_ORDER:
        subset = [rec for rec in records if rec["layer"] == "L-A" and rec["form_id"] == form_id]
        rows = [row for rec in subset for row in rec["per_field"]]
        cells = {key: sum(1 for row in rows if row["decision"] == key) for key in DECISIONS}
        add(
            f"| `{form_id}` | {FORM_DIMENSIONS[form_id]} | {len(rows)} | {cells['offered']} | "
            f"{cells['abstained']} | {cells['missing']} | {cells['sensitive_skipped']} | "
            f"{cells['not_fillable']} | {cells['already_filled']} |"
        )
    add("")
    add(
        "Reading of 2.1: **form markup has no vote in abstention; it only has a vote in field "
        "identification.** `abstained` is 0 in every form variant, and no markup suppresses a "
        "tailored answer. Every column that does move moves for a named reason: `missing` where "
        "a label stopped being recognisable, `offered` where a control is now refused rather "
        "than answered wrongly (section 5 row 1), `not_fillable` where the page had locked a "
        "control, whether by `readonly` or by `disabled` (section 5 rows 2 and 3), "
        "`sensitive_skipped` where the form simply carries one more "
        "identity control, and `already_filled` where the page pre-filled one. The full "
        "movement list is below."
    )
    add("")
    add(
        "Movements against the `form_01_baseline` column, computed from the table above: "
        + (", ".join(movements) if movements else "none")
        + ". Three different things move a cell, and this row is what separates them: a "
        "form-shape difference that the dimension under test is supposed to create (the "
        "extra sensitive control on `form_02_naming`, the Chinese-only label on "
        "`form_06_bilingual`), a control an earlier round now refuses rather than answers "
        "wrongly (section 5 rows 1, 2 and 3), and the page-side pre-fill that exists to test "
        "edit-wins."
    )
    add("")
    add("### 2.2 Profile and posting (L-B and L-C)")
    add("")
    add("| run | resume | posting | offered | abstained | missing | sensitive | not_fillable | already_filled | retrieval active |")
    add("|---|---|---|---:|---:|---:|---:|---:|---:|---|")
    for rec in records:
        if rec["layer"] not in {"L-B", "L-C"}:
            continue
        cells = rec["counts"]
        add(
            f"| `{rec['run_id']}` | `{rec['resume_id']}` | `{rec['jd_id']}` | {cells['offered']} | "
            f"{cells['abstained']} | {cells['missing']} | {cells['sensitive_skipped']} | "
            f"{cells['not_fillable']} | {cells['already_filled']} | "
            f"{'yes' if rec['retrieval_active'] else 'no'} |"
        )
    add("")
    abstain_runs = [rec for rec in records if rec["counts"]["abstained"]]
    abstain_profiles = sorted({rec["resume_id"] for rec in abstain_runs})
    abstain_jds = sorted({rec["jd_id"] for rec in abstain_runs})
    add(f"Reading of 2.2: abstentions appear in {len(abstain_runs)} run(s), on profile(s) "
        f"{abstain_profiles} and posting(s) {abstain_jds}.")
    if abstain_runs:
        add("And in each case the withheld fields are the ones whose answer has to be tailored")
        add("to the posting (skills, experience, project). The mechanism is visible in the")
        add("records: `components_present` carries the retrieved score, and the reason string")
        add("names the component that fell under the threshold. Nothing abstains on a")
        add("personal or education fact, which is the documented design of")
        add("`services._evidence_for_field`. Round 3 narrowed which fields those are: the")
        add("employer, job title, internship period and project name are facts about the")
        add("candidate rather than answers tailored to the posting, so they are no longer")
        add("eligible to abstain (section 5 row 4).")
    else:
        add("And the mechanism is recorded per field in `components_present` / `reasons`.")
    add("")

    # ------------------------------------------- 2.3 missing tracks completeness
    add("### 2.3 `missing` tracks profile completeness")
    add("")
    add("Read from the L-B runs only: same form, same posting, the resume is the one variable.")
    add("")
    add("| profile | `missing` count |")
    add("|---|---:|")
    for resume_id, count in zip(
        ("full_profile", "sparse_profile", "minimal_profile"), profile_missing
    ):
        add(f"| `{resume_id}` | {count} |")
    add("")
    add(
        "The three are strictly increasing - "
        + " < ".join(str(value) for value in profile_missing)
        + " - which is what makes the column readable at all: `missing` is tracking how much "
        "the candidate supplied, not noise. This matters for section 2.1, where `missing` is "
        "the only column a form shape is allowed to move. The ordering is asserted as a "
        "machine check, so it cannot quietly stop holding."
    )
    add("")

    # ------------------------------------------------------- 3. per-form invariants
    add("## 3. The four hard constraints, per form")
    add("")
    add("Each cell is the number of runs of that form in which the constraint held, over the")
    add("number of runs of that form in the matrix.")
    add("")
    add("| form | H2 no submit | H3 no plaintext | H5 no document number | H6 missing means null |")
    add("|---|---|---|---|---|")
    for form_id in FORM_ORDER:
        subset = [rec for rec in records if rec["form_id"] == form_id]
        cells: list[str] = []
        cells.append(
            f"{sum(1 for rec in subset if not rec['invariants']['submit_clicked'])}/{len(subset)}"
        )
        cells.append(
            f"{sum(1 for rec in subset if not rec['invariants']['persisted_text_found'])}/{len(subset)}"
        )
        cells.append(
            f"{sum(1 for rec in subset if not rec['invariants']['identity_doc_echoed'])}/{len(subset)}"
        )
        h6_ok = sum(1 for rec in subset if _h6_holds(rec))
        cells.append(f"{h6_ok}/{len(subset)}")
        add(f"| `{form_id}` | " + " | ".join(cells) + " |")
    add("")
    add("H2 evidence, in full: no value is offered for a control whose type is submit,")
    add("button, reset, image, file, password or hidden (`not_fillable` in every run); the")
    add("OpenAPI surface exposes exactly the five documented endpoints and none of them")
    add("writes or submits; and the static server's access log over the whole matrix contains")
    add(f"**{checks['access_log_posts']} POST requests** against {checks['access_log_gets']} GET requests.")
    add("Residual gap, stated: *clicking* the submit control in a real browser is not exercised")
    add("here. `extension/scripts/browser_check.mjs` covers that on the demo page, and")
    add("`scripts/manual_panel_check.md` covers it per form by hand.")
    add("")
    add("H5 evidence, in full: every identity-document control is reported")
    add("`sensitive_skipped` with an empty `value_hash`; the canary value planted on the pages")
    add("never appears in any response body in any run.")
    add("")
    add("**H5 boundary definition:** `server/README.md` section 4.3, *Definition of "
        "\"transmitted\" in H5* - link `server/README.md#43-definition-of-transmitted-in-h5`.")
    add("A value counts as **transmitted** when it leaves this machine, reaches a model or a")
    add("third party, or is written to durable storage. It does **not** count as transmitted")
    add("when it stays in memory on this machine and is dropped before any of those happens.")
    add("")
    add("Measured behaviour, restated against that definition rather than around it: the content")
    add("script's never-read list covers `password` and `file` only, so a document number that is")
    add("already typed into a page **does** cross the loopback socket to the local server, where")
    add("it is dropped - it never reaches a model, is never echoed to the panel, is never used as")
    add("a value and is never written to disk. Residual risk, named: a process already running on")
    add("this machine could observe that loopback socket.")
    add("")
    add("The stronger option - withholding the value at the page - was considered and not taken")
    add("this round. Doing it would require the content script to know the document-number")
    add("patterns, which is a second implementation of a policy `server/field_map.SENSITIVE_PATTERNS`")
    add("owns and the one thing `server/README.md` section 3 forbids. The clean version is a")
    add("two-phase scan (shape first, values only for the fields the server did not refuse), which")
    add("is a design change, so it is recorded as a question for a later round.")
    add("")

    # ------------------------------------------------------------------ 4. L2
    add("## 4. L2 - what a human still has to judge")
    add("")
    add("The script does not grade L2. It selects the fields and writes the questions to")
    add("`artifacts/form_matrix/l2_review.md`, with the verdict column left empty.")
    add("")
    add("Selected fields and the selection rule are in that file. Note one consequence of H3")
    add("that matters for how a reviewer works: the run log holds hashes and lengths, never")
    add("values, so L2 cannot be completed from the log alone. It has to be done against a")
    add("live panel or a re-run. That is deliberate, not an oversight.")
    add("")
    add(
        f"The generated sheet is {len(l2_text.splitlines())} lines long. It is written to "
        "`l2_review.md`; when that file already carries a reviewer's verdicts it is left "
        "alone and the fresh sheet goes to `l2_review.generated.md` instead, because a "
        "filled-in sheet is evidence and not a cache."
    )
    add("")
    add("H3 scan coverage, for the record: "f"{h3['artifact_files_scanned']} artifact file(s) and "
        f"{h3['temp_files_scanned']} temp file(s) were scanned against {h3['sentinels']} "
        "sentinel string(s); hits: "
        f"{len(h3['artifact_hits']) + len(h3['temp_hits'])}. "
        f"`chrome.storage.local` status: `{h3['chrome_storage_local']}` - the store exists only "
        "inside an extension context, so it is covered by `scripts/manual_panel_check.md`, not "
        "by this script.")
    add("")

    # ------------------------------------------------------- 5. failures
    add("## 5. Known failures and attribution")
    add("")
    add("Ordered by **severity**, not by discovery order. The rule, stated so it can be argued")
    add("with: *user-visible error* (`high`) > *classification gap* (`medium`) > *reporting gap*")
    add("(`low`) > *untested* (`low`). A `fixed in round 2` or `fixed in round 3` row is kept")
    add("rather than deleted: it was a real failure of an earlier round, and the fix is what the")
    add("change log in section 8 records. Three rows are open, all three recorded as design")
    add("questions for a later round rather than carried silently.")
    add("")
    add("**Row numbers in this section are display positions**, and a cross-reference that says")
    add("`row N` means the Nth row of the table below. Two rows also carry a name from the")
    add("round-2 L2 sheet, because that sheet, the regression tests and the change log all use")
    add("it: **`7a` is the experience / project fact split and `7b` is the `missing` reason")
    add("attribution**. They are written as names and never as `#7a`, so a named row cannot be")
    add("mistaken for row 7.")
    add("")
    severity_parts = [
        f"{sum(1 for item in findings if item.get('severity') == level)} {level}"
        for level in ("high", "medium", "low")
    ]
    add(
        f"Nine findings: {', '.join(severity_parts)}; "
        f"{sum(1 for item in findings if str(item.get('status', '')).startswith('fixed'))} fixed "
        "(in round 2 or round 3), "
        f"{sum(1 for item in findings if str(item.get('status', '')).startswith('open'))} "
        "left open (each with the reason it is open), and "
        f"{sum(1 for item in findings if str(item.get('status', '')).startswith('not testable'))} "
        "recorded as not testable in offline mode rather than as open or fixed."
    )
    add("")
    add("Attribution vocabulary, fixed in advance and unchanged this round: `bug` = the system")
    add("produced a wrong result on its own terms; `generation wobble` = the same input gave a")
    add("different result; `edge` = a form or data shape outside what the current design claims")
    add("to cover. **`generation wobble` is not observable in offline mode (see M3)**, so no row")
    add("carries it: the L-D row states why instead.")
    add("")
    add("| # | severity | status | what happened | attribution | evidence |")
    add("|---:|---|---|---|---|---|")
    for index, finding in enumerate(ordered_findings, start=1):
        add(
            f"| {index} | `{finding['severity']}` | {finding['status']} | {finding['what']} | "
            f"`{finding['kind']}` | {finding['evidence']} |"
        )
    add("")
    add("L-D is structurally deterministic in offline mode; see §6.")
    add("")

    # ------------------------------------------------------- 6. limitations
    add("## 6. Limitations")
    add("")
    add("Six required limitations, none omitted:")
    add("")
    add("1. **Not a browser run.** The content script's extraction is mirrored in Python. The")
    add("   real content script is verified separately by `extension/scripts/browser_check.mjs`.")
    add("2. **Offline stub only.** `RJD_OFFLINE=1` for every run, so the drafting is a literal")
    add("   extractor. `fabricated_claims == 0` therefore says the guards and the wiring hold on")
    add("   this data - it is **not** evidence that a live model would not fabricate.")
    add("3. **Stability (generation wobble) is not testable in offline mode.** The stub has no")
    add("   sampler, so any repetition must agree; the L-D probe still runs, and its agreement is")
    add("   a property of the stub rather than a measurement of the product. Stability requires")
    add("   `mode: live_api`; it is not claimed by this matrix.")
    add("4. **`chrome.storage.local` was not inspected.** It exists only inside an extension")
    add("   context, and the matrix runs outside the browser, so this surface is covered by")
    add("   `scripts/manual_panel_check.md`, not by this script.")
    add("5. **Corpus limit still standing.** The similarity scale is the one already documented")
    add("   for the same 54-chunk knowledge base (floor 0.3663, ceiling 0.5633). The knowledge")
    add("   base was not rebuilt and `scripts/calibrate_similarity.py` was not run, so no")
    add("   recalibration is being claimed. Change the corpus and these numbers are void.")
    add("6. **Timing metrics remain disabled** (H8). No duration appears anywhere in this")
    add("   report, and none was measured.")
    add("")
    add("Also outside those six:")
    add("")
    add("- **Dimensions not covered.** No unsaved-draft flow, no multi-step wizard, no same-name")
    add("  repeated controls across sections, no dynamically inserted fields, no iframe or shadow")
    add("  DOM, no `<button>`-based form controls beyond the one absence recorded in section 5,")
    add("  no non-Latin label tested beyond Chinese, and no right-to-left text.")
    add("- **`disabled` controls are measured now, in one shape only.** Round 3 plants a")
    add("  `disabled` input on `form_05_traps` and both layers refuse it (section 5 row 3), so the")
    add("  family of mistake behind the round-2 `readonly` finding is closed at the level this")
    add("  matrix tests. Still uncovered: a `disabled` `<select>` or `<textarea>`, and a control")
    add("  the page disables *after* the scan has run. The matrix plants neither.")
    add("- **The page-side half of each fix is unverified in a browser.** The server-side")
    add("  refusals and the fact / tailored split are pinned by")
    add("  `tests/test_form_matrix_regressions.py`; the content script's own `readonly` and")
    add("  `disabled` refusals and its section-context reporting are covered only by")
    add("  `scripts/manual_panel_check.md`, and by `extension/scripts/browser_check.mjs` for the")
    add("  demo page it drives.")
    add("- **Side panel rendering is covered by the manual checklist, not by this script.**")
    add("  `scripts/manual_panel_check.md` is the procedure; `chrome.sidePanel.open()` refuses")
    add("  a synthetic gesture, which is why it cannot be automated.")
    add("")
    add("Source fingerprint (H7):")
    add("")
    add("| file | sha256 |")
    add("|---|---|")
    for rel, digest in fingerprint["files"].items():
        add(f"| `{rel}` | `{digest}` |")
    add("")
    add("Full digests, not prefixes: this table exists to be recomputed, and a prefix cannot be")
    add("checked. The same values are in `artifacts/form_matrix/source_fingerprint.json`, and")
    add("both come from one `source_fingerprint()` call, so neither can drift from the files it")
    add("names.")
    add("")
    add(f"Abstention threshold read back: **{fingerprint['abstention_threshold']}**, weights")
    add(f"retrieval {fingerprint['weights']['retrieval']} / llm_self {fingerprint['weights']['llm_self']},")
    add(f"abstain-on-either **{fingerprint['abstain_on_either_component']}**. None of these were changed.")
    add("")

    # ------------------------------------------------------- 7. live spot-check
    add("## 7. Live spot-check")
    add("")
    add("Why exactly two runs, and these two. The offline matrix has three blind spots it cannot")
    add("close by itself: (a) the classification trap, the section-naming case in section 5 row 1;")
    add("(b) the sparsest profile, where `missing` is densest and a model has the most room to")
    add("invent; and (c) the cross-domain posting, the only configuration that produces")
    add("abstentions. Two cells cover all three, which makes them the smallest set worth paying")
    add("for:")
    add("")
    add("- `form_03_help_text` x `full_profile` x `jd_named`")
    add("- `form_05_traps` x `sparse_profile` x `jd_implied`")
    add("")
    add("The rest of the matrix is deliberately *not* re-run live. `fabricated_claims == 0` in")
    add("offline mode is structurally zero - the stub is a literal extractor, so it cannot invent")
    add("- and only a real model can turn that into a zero that was earned. When these two cells")
    add("are run, their results go to `artifacts/form_matrix/live_spot_check.md` and are never")
    add("merged into the tables above: they are a different mode, a different model and a")
    add("different question.")
    add("")
    if live and live.get("status") == "ok":
        add(
            f"Driver: `scripts/live_spot_check.py`. Mode **{live.get('mode', '')}**, model "
            f"**{live.get('model', '')}**, condition {live.get('condition', '')}, "
            f"{live.get('runs', 0)} run(s). Cost: {live.get('cost_note', 'a fraction of a cent')}."
        )
        add("")
        add("| cell | controls | offered | abstained | missing | sensitive | not_fillable | model-drafted | fabricated claims |")
        add("|---|---:|---:|---:|---:|---:|---:|---:|---:|")
        for row in live.get("rows", []):
            add(
                f"| `{row['cell']}` | {row['fields']} | {row['offered']} | {row['abstained']} | "
                f"{row['missing']} | {row['sensitive_skipped']} | {row['not_fillable']} | "
                f"{row['model_drafted']} | {row['fabricated']} |"
            )
        add("")
        add(f"**{live.get('headline', '')}**")
        add("")
        add(live.get("note", ""))
        add("")
    elif live and live.get("status") == "deferred":
        add(f"Live spot-check deferred: {live.get('reason', 'cost')}.")
        add("")
    else:
        add("Live spot-check deferred: cost. The offline zero-fabrication figure remains")
        add("structurally trivial, not evidence.")
        add("")

    # ------------------------------------------------------------ 8. change log
    add("## 8. Change log - three rounds, cell by cell")
    add("")
    add("Three columns, because two rounds of fixes are stacked on top of each other:")
    add("**round 1** is the untouched baseline, **round 2** is the first round of fixes and")
    add("**round 3** is this run. Neither before-column is typed in. Both are recomputed from")
    add("the run files left on disk (`runs_before_round2.jsonl`, `runs_before_round3.jsonl`)")
    add("by the same function that derives the after-column, and that recomputation is")
    add("asserted - a transcription that disagreed with the records fails a machine check")
    add("instead of printing quietly.")
    add("")
    add("Nothing here was adjusted to make a number read better. A metric that is not in this")
    add("table did not move.")
    add("")
    add("| metric | round 1 | round 2 | round 3 | span 1-3 | why it moved |")
    add("|---|---:|---:|---:|---|---|")
    for label, key, why in CHANGE_ROWS:
        before = change_log["round1"].get(key, "absent")
        middle = change_log["round2"].get(key, "absent")
        after = change_log["round3"].get(key, "absent")
        if before == middle == after:
            span = "unchanged"
        elif isinstance(before, int) and isinstance(after, int):
            span = f"{after - before:+d}"
        else:
            span = "changed"
        add(f"| {label} | `{before}` | `{middle}` | `{after}` | {span} | {why} |")
    add("")
    add("Every row that moved, and why the move is forced rather than chosen:")
    add("")
    add("- **Finding `7a` (section 5 row 4) moved four fields, in exactly one run.** `Company")
    add("  name`, `Job title`, `Internship period` and `Project name` are facts the profile")
    add("  states, not answers tailored to a posting, so they left")
    add("  `services.TAILORED_CATEGORIES` and stopped inheriting the posting's retrieval")
    add("  score. All four were `abstained` in exactly one cell - `" + LC_CROSS_DOMAIN_RUN + "`")
    add("  - so that run gains 4 `offered` and loses 4 `abstained`. Those eight cells are the")
    add("  whole of its effect on the matrix; the other eight runs are byte-identical in")
    add("  their decision counts.")
    add("- **Finding `7b` (section 5 row 5) moved no count at all.** A fact-shaped field whose")
    add("  fact is absent from the profile was already `missing`, so the fix changes the")
    add("  *reason* it reports and the components it claims to have measured. It is listed")
    add("  here as a report repair rather than a number, because claiming a count movement")
    add("  for a change that only touched a string would be a fabrication.")
    add("- **The `disabled` fix (section 5 row 3) added a control.** The input on")
    add("  `form_05_traps` appears in two runs, so it adds 2 to the field total and 2 to")
    add(f"  `not_fillable`, and 0 to `offered` - which is why the eligible denominator ({eligible})")
    add("  does not move at all.")
    add("")
    add("One round-2 prediction could not hold, and it is arithmetic rather than opinion. The")
    add("round-2 brief expected `form_03 offered` to fall 17 -> 16 **and** `form_03 missing` to")
    add("fall 7 -> 6 at the same time. The field total for that form is fixed, `abstained` and")
    add("`sensitive_skipped` cannot move in offline mode, and `not_fillable` is unchanged on")
    add("form_03 - so a control leaving `offered` has exactly one bucket left to land in, and")
    add("it is `missing`. The recorded outcome was `offered` 17 -> 16 with `missing` 7 -> 8, and")
    add("round 3 disturbed neither column.")
    add("")
    add("`sensitive_skipped` is 42 in all three columns and `already_filled` is 2 in all three:")
    add("no identity control and no page pre-fill was added or removed in any round. `abstained`")
    add("did move this round, 9 -> 5, and every field it lost is named above; the five that")
    add("remain are `skills` / `experience` / `project` fields whose answer genuinely has to be")
    add("tailored, which is what abstention is for.")
    add("")
    add("Three things changed in the *report* itself without a count changing. Each repairs an")
    add("earlier round rather than editing it quietly:")
    add("")
    add("- Round 1's section 2.1 called `sensitive_skipped` constant across form variants. It is")
    add("  not: `form_02_naming` carries 3 identity controls where every other form carries 2, so")
    add("  the column moves by +1 there. The reading now names that cause instead of denying it,")
    add("  and the movement list under the table enumerates it.")
    add("- The fingerprint table prints the full digest. A 16-character prefix cannot be")
    add("  recomputed against the file it names, and a table that cannot be checked is decoration.")
    add("- Round 2's L2 sheet inferred, from `source = \"none\"`, that the classifier had *never*")
    add("  placed the absent GPA control in the education category. The record says otherwise:")
    add("  the category is `education`, and the field is `missing` because the profile carries no")
    add("  GPA - which is exactly what finding `7b` now says out loud. The finding was right")
    add("  about the symptom and wrong about the mechanism, and both halves are recorded here")
    add("  rather than letting a wrong explanation stand next to a correct fix.")
    add("")
    return "\n".join(lines) + "\n"


def _h6_holds(rec: dict[str, Any]) -> bool:
    for row in rec["per_field"]:
        if row["decision"] == "missing" and not row["missing"]:
            return False
        if row["decision"] in {"missing", "abstained", "sensitive_skipped"} and row["value_hash"]:
            return False
        if row["decision"] == "offered" and not row["value_hash"]:
            return False
    return True


#: The three verdicts L2 admits. Kept next to the reader so the tokens the
#: report counts and the tokens a reviewer types are the same list.
L2_VERDICTS = ("agree", "disagree", "unclear")


def has_hand_verdicts(text: str) -> bool:
    """Does this sheet already carry a reviewer's judgement?"""
    return any(count for count in l2_verdict_counts(text).values())


def l2_verdict_counts(text: str) -> dict[str, int]:
    """Read the verdict column back out of a hand-filled L2 sheet.

    Column-position based rather than a token count, because the prose of that
    file legitimately says "the two `disagree` rows" and "an `agree` whose reason
    is wrong". Only cells in the column whose *header* says `verdict` are counted,
    which is the one place a verdict can live.
    """
    counts = {token: 0 for token in L2_VERDICTS}
    column: int | None = None
    for line in text.splitlines():
        if not line.startswith("|"):
            column = None
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        lowered = [cell.lower() for cell in cells]
        if column is None:
            if "verdict" in lowered:
                column = lowered.index("verdict")
            continue
        if column >= len(cells):
            continue
        token = cells[column].strip("`").strip().lower()
        if token in counts:
            counts[token] += 1
    return counts


def render_l2(records: list[dict[str, Any]], resumes: dict[str, Resume]) -> str:
    """One run from L-A, one from L-C, three fields each. Verdict left blank."""
    lines: list[str] = []
    add = lines.append
    add("# L2 - human judgement sheet")
    add("")
    add("Not graded by the script. Fill the last two columns in by hand.")
    add("")
    add("Selection rule: the first run of L-A and the first run of L-C in run order, then the")
    add("first three fields of each whose decision is `offered`, taken in field order. Fields")
    add("are chosen this way so the reviewer spends their attention on values that were actually")
    add("offered, which is where a wrong answer would reach a user.")
    add("")
    add("Values are **not** in this file: the run log stores a hash and a length only (H3).")
    add("To judge a row, re-run the same cell and read the panel, or read the live page.")
    add("Reproduce the *questions* with:")
    add("")
    add("```")
    add("python scripts/run_form_matrix.py")
    add("```")
    add("")
    add("This file is hand-filled once and is never overwritten while it carries verdicts;")
    add("a later run writes `l2_review.generated.md` instead.")
    add("")
    add("## Question set 1 - fields the system offered")
    add("")
    add("Question for every row: *does this value really come from the candidate's profile,")
    add("and is it in the correct field? Should it have been withheld instead?*")
    add("")
    add("| run_id | field_id | label | system_decision | system_reason | question for the reviewer | verdict | note |")
    add("|---|---|---|---|---|---|---|---|")

    picked: list[tuple[str, dict[str, Any]]] = []
    for layer in ("L-A", "L-C"):
        for rec in records:
            if rec["layer"] != layer:
                continue
            offered = [row for row in rec["per_field"] if row["decision"] == "offered"][:3]
            for row in offered:
                picked.append((rec["run_id"], row))
            break

    for run_id, row in picked:
        reasons = "; ".join(row["reasons"]) or "(no reason string on this row)"
        question = (
            "Does this value really come from the candidate's profile, and is it in the "
            "correct field? Should it have been withheld (abstained/missing) instead?"
        )
        add(
            f"| `{run_id}` | `{row['field_id']}` | {row['label'] or '(no label)'} | "
            f"`{row['decision']}` | {reasons[:80]} | {question} | | |"
        )
    add("")
    if not picked:
        add("(no `offered` field was found in the sampled runs)")
        add("")
    add("## Question set 2 - fields the system refused")
    add("")
    add("These are the fields where the system declined. The question is the inverse: was")
    add("refusing right, or did it withhold something the profile plainly states?")
    add("")
    add("| run_id | field_id | label | system_decision | system_reason | question | verdict | note |")
    add("|---|---|---|---|---|---|---|---|")
    refused = 0
    for layer in ("L-A", "L-C"):
        for rec in records:
            if rec["layer"] != layer:
                continue
            rows = [row for row in rec["per_field"] if row["decision"] in {"abstained", "missing"}][:3]
            for row in rows:
                refused += 1
                reasons = "; ".join(row["reasons"]) or "(no reason string on this row)"
                add(
                    f"| `{rec['run_id']}` | `{row['field_id']}` | {row['label'] or '(no label)'} | "
                    f"`{row['decision']}` | {reasons[:80]} | "
                    f"Was refusing right - and does the profile actually hold that answer? | | |"
                )
            break
    if not refused:
        add("| - | - | - | - | - | (no refused field in the sampled runs) | | |")
    add("")
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--verbose", action="store_true", help="print every passing check")
    parser.add_argument(
        "--out-dir",
        default=str(OUT_DIR),
        help="where runs.jsonl / report.md / l2_review.md go (default artifacts/form_matrix)",
    )
    args = parser.parse_args(argv)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    tmp_dir = out_dir / "tmp_run"
    tmp_dir.mkdir(parents=True, exist_ok=True)

    # Offline, deterministic, no action log, and an embedder that never reaches out.
    os.environ["RJD_OFFLINE"] = "1"
    os.environ.pop("RJD_SERVER_LOG", None)
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
    os.environ["TEMP"] = str(tmp_dir)
    os.environ["TMP"] = str(tmp_dir)

    report = Report(verbose=args.verbose)

    print("=" * 74)
    print("Form matrix - browser assistant under field and profile diversity")
    print("=" * 74)

    # ------------------------------------------------------------------ data
    report.section("0. Test data and forms")
    resumes_list = load_resumes()
    jds_list = load_jds()
    resumes = {r.resume_id: r for r in resumes_list}
    jds = {j.jd_id: j for j in jds_list}
    forms: dict[str, Form] = {}
    for path in sorted(FORM_DIR.glob("*.html")):
        forms[path.stem] = Form(path.stem, path, path.read_text(encoding="utf-8"))

    report.equal(len(resumes_list), 5, "five synthetic resumes are present")
    report.equal(len(jds_list), 3, "three synthetic postings are present")
    report.equal(len(forms), 6, "six simulated forms are present")
    for expected in RESUME_ORDER:
        report.check(expected in resumes, f"resume {expected} exists")
    for expected in FORM_ORDER:
        report.check(expected in forms, f"form {expected} exists")
    for expected in JD_ORDER:
        report.check(expected in jds, f"posting {expected} exists")

    # declared_skills must equal what the renderer + taxonomy actually produce,
    # or the fabrication check would be comparing against a wish list.
    from server import services as server_services
    from src.taxonomy import canonicalise, match_skills

    for resume in resumes_list:
        prepared = server_services.prepare_inputs(
            resume.profile, resume.authorised_modules, jds["jd_named"].text
        )
        found = sorted({canonicalise(s) for s in match_skills(prepared.rendered.text)})
        report.equal(
            sorted(resume.declared_skills),
            found,
            f"{resume.resume_id}: declared_skills equals the skills the renderer produces",
        )

    for jd in jds_list:
        report.equal(
            sorted(jd.expected_skills),
            sorted(match_skills(jd.text)),
            f"{jd.jd_id}: expected_jd_skills matches the taxonomy",
        )

    # H4 - synthetic addresses only.
    addresses: list[str] = []
    for payload in list(resumes_list) + list(jds_list):
        blob = json.dumps(payload.data, ensure_ascii=False)
        addresses.extend(re.findall(r"[\w.\-+]+@[\w\-]+\.[\w.\-]+", blob))
    bad_domains = sorted(
        {a.split("@", 1)[1] for a in addresses if not a.endswith(("example.com", "example.edu"))}
    )
    report.check(bool(addresses), "the matrix contains email addresses to check")
    report.equal(bad_domains, [], "every address is on example.com or example.edu (H4)")

    # H5 - the resumes and postings themselves must carry no document number.
    id_shaped: list[str] = []
    for payload in list(resumes_list) + list(jds_list):
        blob = json.dumps(payload.data, ensure_ascii=False)
        id_shaped.extend(re.findall(r"\b[A-Z]{1,2}\d{6,}[A-Z]?\b", blob))
        id_shaped.extend(re.findall(r"\b\d{8,}\b", blob))
    report.equal(id_shaped, [], "no resume or posting contains a document-number-shaped value (H5)")

    # Every form must be able to carry the constraints this matrix tests.
    for form_id in FORM_ORDER:
        form = forms[form_id]
        report.check(PROTOTYPE_NOTICE in form.html, f"{form_id} is labelled as a prototype")
        report.check('action="#"' in form.html, f"{form_id} has an inert form action")
        report.check(
            "event.preventDefault()" in form.html and "window.__submitAttempts = 0" in form.html,
            f"{form_id} blocks submission and counts attempts on the page",
        )
        report.check("<textarea" in form.html, f"{form_id} has at least one open question")
        report.check(
            ("passport" in form.html.lower()) or ("nric" in form.html.lower()) or ("护照" in form.html),
            f"{form_id} carries at least one identity-document control (H5 must be testable)",
        )

    # The built content script is the thing that would submit if anything did.
    content_js = EXT_DIST / "content.js"
    if content_js.exists():
        bundle = content_js.read_text(encoding="utf-8")
        for forbidden, why in (
            (".submit(", "form submission"),
            ("requestSubmit", "form submission"),
            ("new SubmitEvent", "form submission"),
        ):
            report.check(forbidden not in bundle, f"dist/content.js has no {why} call ({forbidden})")
        report.check(
            "NEVER_READ_TYPES" in bundle,
            "dist/content.js still carries the never-read list",
        )
    else:
        report.check(False, "extension/dist/content.js exists", "run `npm run build` in extension/")

    # --------------------------------------------------------------- services
    static_port = free_port()
    backend_port = free_port()
    page_base = f"http://127.0.0.1:{static_port}"
    api_base = f"http://127.0.0.1:{backend_port}"
    print(f"\n[static]  {page_base}  ->  demo/form_matrix/")
    print(f"[backend] {api_base}  (offline, token required)")

    httpd = start_static_server(static_port)

    from server.services import KnowledgeBaseProvider

    kb_provider = KnowledgeBaseProvider(persist_dir=out_dir / "kb_index" / "chroma_db")
    kb = kb_provider.get()
    retrieval_available = kb is not None
    print(f"[retrieval] available: {retrieval_available}" + ("" if kb is not None else f" ({kb_provider.error})"))

    backend_server = start_backend(backend_port, kb_provider)
    import httpx

    client = httpx.Client(base_url=api_base, timeout=120.0, headers={"X-RJD-Token": TOKEN})
    records: list[dict[str, Any]] = []
    fingerprint = source_fingerprint()

    try:
        # ------------------------------------------------------------- health
        report.section("1. Contract, health and the no-submit surface")
        health = client.get("/health")
        report.equal(health.status_code, 200, "/health answers without a token")
        hpayload = health.json()
        report.equal(hpayload.get("mode"), "offline_stub", "/health reports the offline mode honestly")
        report.equal(hpayload.get("bind_host"), "127.0.0.1", "/health reports a loopback bind")
        report.equal(hpayload.get("auth_required"), True, "/health says a token is required")

        unauth = httpx.post(f"{api_base}/generate", json={"fields": []}, timeout=10)
        report.equal(unauth.status_code, 401, "/generate without a token is rejected")

        paths = set(client.get("/openapi.json").json().get("paths", {}))
        # Six now: `/extract_resume` joined the surface in round 9-10. It reads
        # text the panel extracted and persists nothing, so "none of them a write"
        # still holds - see server/README.md section 2.
        report.equal(
            paths,
            {"/health", "/scan", "/generate", "/jd/fetch", "/jd/analyze", "/extract_resume"},
            "the API exposes exactly the six documented endpoints, none of them a write",
        )
        report.check(
            not any("fetch" in p and "jd" not in p for p in paths),
            "no endpoint other than /jd/fetch touches the network",
        )

        # --------------------------------------------------------------- runs
        report.section("2. The run matrix")
        plan = build_run_plan()
        print(f"  {len(plan)} runs planned")
        for index, spec in enumerate(plan, start=1):
            form = forms[spec.form_id]
            resume = resumes[spec.resume_id]
            jd = jds[spec.jd_id]
            page_url = f"{page_base}/{form.form_id}.html"

            # A real page load, so the access log is evidence about this URL.
            loaded = httpx.get(page_url, timeout=10)
            report.check(loaded.status_code == 200, f"{spec.form_id} serves over 127.0.0.1 (H1)")

            if not form.fields:
                form.fields = extract_fields(form.html)

            scan = client.post(
                "/scan",
                json={"url": page_url, "page_title": form.form_id, "fields": form.fields},
            )
            if scan.status_code != 200:
                report.check(False, f"{spec.run_id}: /scan answers", f"HTTP {scan.status_code}")
                continue
            scanned = scan.json()

            gen = client.post(
                "/generate",
                json={
                    "fields": form.fields,
                    "authorised_modules": resume.authorised_modules,
                    "profile": resume.profile,
                    "jd_text": jd.text,
                    "condition": CONDITION,
                    "url": page_url,
                    "page_title": form.form_id,
                    "overwrite_filled": False,
                    "scanned_field_ids": [row["field_id"] for row in scanned["fields"]],
                },
            )
            if gen.status_code != 200:
                report.check(False, f"{spec.run_id}: /generate answers", f"HTTP {gen.status_code}")
                continue
            generated = gen.json()

            declared = {canonicalise(s) for s in resume.declared_skills}
            record = build_record(
                spec,
                form=form,
                scanned=scanned,
                generated=generated,
                page_url=page_url,
                canary=CANARY,
                declared_skills=declared,
                jd_text=jd.text,
            )
            records.append(record)
            report.check(
                CANARY not in gen.text and PASSWORD_CANARY not in gen.text,
                f"{spec.run_id}: no planted value appears in the /generate body (H5)",
            )
            report.check(
                CANARY not in scan.text,
                f"{spec.run_id}: the planted value is absent from the /scan body too (H5)",
            )
            print(
                f"  [{index:2d}/{len(plan)}] {record['run_id']:<52} "
                f"offered={record['counts']['offered']:2d} "
                f"abstained={record['counts']['abstained']:2d} "
                f"missing={record['counts']['missing']:2d} "
                f"sens={record['counts']['sensitive_skipped']:2d} "
                f"nf={record['counts']['not_fillable']:2d} "
                f"af={record['counts']['already_filled']:2d}"
            )

        report.equal(len(records), len(plan), "every planned run produced a record")

        # ------------------------------------------------ H2: the access log
        report.section("3. H2 - no submission ever reached the network")
        access = list(getattr(httpd, "access_log", []))
        posts = [entry for entry in access if entry["method"] == "POST"]
        gets = [entry for entry in access if entry["method"] == "GET"]
        report.equal(len(posts), 0, "the form server received zero POST requests")
        report.check(
            all(entry["status"] == 200 for entry in gets),
            "every page load succeeded",
            str([e for e in gets if e["status"] != 200][:3]),
        )
        report.check(
            all(CANARY not in entry["path"] for entry in access),
            "no request URL carried a planted value",
        )
        report.check(
            all("127.0.0.1" in rec["page_url"] for rec in records),
            "every run was driven against a loopback page (H1)",
        )
        report.check(
            all(rec["jd_id"] in {"jd_named", "jd_implied", "jd_cross_domain"} for rec in records),
            "every posting came from a local synthetic file, and /jd/fetch was never called (H1)",
        )

        # ------------------------------------------------------ L1 assertions
        report.section("4. L1 - machine checks over every run")

        # 4.1 the six-way partition is exhaustive and exclusive
        bad_partition = [
            rec["run_id"]
            for rec in records
            if not rec["invariants"]["decision_partition_ok"]
        ]
        report.equal(bad_partition, [], "the six decisions partition every field, every run")

        # 4.2 the server's own arithmetic reconciles with a per-field derivation
        mismatch: list[str] = []
        for rec in records:
            derived = rec["counts"]
            server_counts = rec["counts_server"]
            overlap = rec["counts_reconciliation"]["sensitive_and_already_filled_overlap"]
            if server_counts["offered"] != derived["offered"]:
                mismatch.append(f"{rec['run_id']}: offered {server_counts['offered']}/{derived['offered']}")
            if server_counts["abstained"] != derived["abstained"]:
                mismatch.append(f"{rec['run_id']}: abstained {server_counts['abstained']}/{derived['abstained']}")
            if server_counts["missing"] != derived["missing"]:
                mismatch.append(f"{rec['run_id']}: missing {server_counts['missing']}/{derived['missing']}")
            if server_counts["sensitive_skipped"] != derived["sensitive_skipped"]:
                mismatch.append(
                    f"{rec['run_id']}: sensitive "
                    f"{server_counts['sensitive_skipped']}/{derived['sensitive_skipped']}"
                )
            if server_counts["not_fillable"] != derived["not_fillable"]:
                mismatch.append(
                    f"{rec['run_id']}: not_fillable "
                    f"{server_counts['not_fillable']}/{derived['not_fillable']}"
                )
            # already_filled is orthogonal by design: a sensitive control that already
            # holds a value is counted twice by the server. Reconcile, do not pretend.
            if server_counts["already_filled"] != derived["already_filled"] + overlap:
                mismatch.append(
                    f"{rec['run_id']}: already_filled {server_counts['already_filled']} != "
                    f"{derived['already_filled']} + overlap {overlap}"
                )
        report.equal(
            mismatch[:6],
            [],
            "the server's counts reconcile with the per-field derivation (incl. the documented overlap)",
        )
        overlap_runs = sum(
            1 for rec in records if rec["counts_reconciliation"]["sensitive_and_already_filled_overlap"]
        )
        print(
            f"  note: the brief expects six mutually exclusive counts summing to the field total.\n"
            f"        That holds for this script's derivation, which classifies by precedence.\n"
            f"        It does NOT hold for the server's raw counts: {overlap_runs} run(s) contain a\n"
            f"        control that is both sensitive and already filled, and the server counts it in\n"
            f"        both buckets - as `server/schemas.py:GenerateCounts` documents. The check above\n"
            f"        reconciles the two rather than asserting the brief's arithmetic."
        )

        # 4.3 H2 / H5 / H6 per field
        report.check(
            all(not rec["invariants"]["submit_clicked"] for rec in records),
            "no run reports a submission",
        )
        report.check(
            all(
                row["value_hash"] == ""
                for rec in records
                for row in rec["per_field"]
                if row["sensitive"]
            ),
            "every sensitive control has an empty value hash",
        )
        report.check(
            all(
                not row["value_hash"]
                for rec in records
                for row in rec["per_field"]
                if row["decision"] in {"missing", "abstained", "sensitive_skipped"}
            ),
            "no value exists behind a missing, abstained or sensitive decision",
        )
        report.check(
            all(
                not row["missing"] or row["value_hash"] == ""
                for rec in records
                for row in rec["per_field"]
            ),
            "a field reported missing never carries a value (H6)",
        )
        report.check(
            all(not rec["invariants"]["identity_doc_echoed"] for rec in records),
            "no planted document value appears anywhere in any response (H5)",
        )
        report.check(
            all(not rec["invariants"]["fabricated_claims"] for rec in records),
            "no run offers a skill the profile does not declare (fabrication check)",
        )

        # 4.4 max_length and option lists
        over_limit = [
            (rec["run_id"], row["field_id"], row["value_length"], row["max_length"])
            for rec in records
            for row in rec["per_field"]
            if row["decision"] == "offered"
            and row["max_length"]
            and row["value_length"] > row["max_length"]
        ]
        report.equal(over_limit, [], "no offered value exceeds its control's maxlength")

        offered_without_conf = [
            rec["run_id"]
            for rec in records
            if any(
                row["decision"] == "offered" and not row["needs_user_confirmation"]
                for row in rec["per_field"]
                if row["confidence"] < 0.7 and row["source"]
            )
        ]
        print(f"  (offered values below 0.7 confidence with the confirmation flag cleared: {len(offered_without_conf)})")

        # 4.5 the classification expectations each form exists to test
        report.section("5. Form-specific expectations")
        findings: list[dict[str, Any]] = []

        def rows_for(form_id: str, name: str) -> list[dict[str, Any]]:
            return [
                row
                for rec in records
                if rec["form_id"] == form_id
                for row in rec["per_field"]
                if row["name"] == name or row.get("element_id") == name
            ]

        # Every identity control, on every form, in every run.
        sensitive_rows = [
            row for rec in records for row in rec["per_field"] if row["sensitive"]
        ]
        report.check(bool(sensitive_rows), "identity controls were found and classified")
        report.check(
            all(row["decision"] == "sensitive_skipped" for row in sensitive_rows),
            "every identity control is reported sensitive_skipped",
            str(sorted({row["decision"] for row in sensitive_rows})),
        )

        # form_02: all three identity spellings resolve
        for name in ("passportNumber", "passport_no", "nricNumber"):
            rows = rows_for("form_02_naming", name)
            report.check(
                bool(rows) and all(row["sensitive"] for row in rows),
                f"form_02: {name} is detected as an identity control (camelCase split)",
            )

        # form_03: the legend-only control must not be answered
        extra_rows = rows_for("form_03_help_text", "extra_1")
        report.check(
            bool(extra_rows) and all(row["decision"] != "offered" for row in extra_rows),
            "form_03: the legend-only control gets no value (it cannot be named)",
        )
        name2_rows = rows_for("form_03_help_text", "name_2")
        name2_offered = [row for row in name2_rows if row["decision"] == "offered"]
        name2_decisions = sorted({row["decision"] for row in name2_rows})
        report.check(
            bool(name2_rows),
            "form_03: the ambiguous 'Name' control under an 'Employer details' legend was scanned",
        )
        # M1, report section 5 row 1. The fix is *asserted*, not merely described:
        # after round 2 this control carries no value, because a section heading
        # may not name a field. `name_2` was offered in every round-1 run, so
        # `len(name2_rows)` is also the round-1 offered count.
        report.equal(
            name2_decisions,
            [ROUND3_EXPECTED["name_2_decision"]],
            "form_03: the employer control is no longer answered with the candidate's name (M1)",
        )
        report.check(
            not name2_offered,
            "form_03: no run offers the candidate's full name into the employer box (M1)",
        )
        findings.append(
            {
                "key": "employer_classification",
                "severity": "high",
                "order": 1,
                "status": "fixed in round 2",
                "what": (
                    "form_03: the employer control is labelled `Name` inside an `Employer details` section, "
                    "so the generic name fallback (`_FALLBACK_NAME`) classified it as the candidate's own "
                    "name and the assistant offered the candidate's full name into the employer box "
                    f"({len(name2_rows)} run(s) in round 1). **Round 2:** section text is context and may no "
                    "longer name a field, so the control is refused (`missing`) rather than filled with the "
                    "wrong fact."
                ),
                "kind": "bug",
                "evidence": (
                    "round-1 records: field `name_2`, label `Name`, decision `offered`, source "
                    "`personal_info.full_name`; round-2 records: decision `missing`; regression "
                    "`tests/test_form_matrix_regressions.py::test_legend_never_names_a_field`; source "
                    "`server/field_map.classify` + `extension/src/content.ts:isSectionLevelText`"
                ),
            }
        )

        # form_04: the three maxlength tiers
        unanswerable_fields: list[str] = []
        for name, limit in (("linkedin", 50), ("project_description", 300), ("internship_description", 1000)):
            rows = rows_for("form_04_maxlength", name)
            trimmed = [row for row in rows if "trimmed" in row["message_kinds"]]
            unanswerable = [row for row in rows if "length_unanswerable" in row["message_kinds"]]
            report.check(
                all(row["value_length"] <= limit for row in rows if row["decision"] == "offered"),
                f"form_04: the {limit}-character control is never over its limit",
            )
            print(
                f"  form_04 {name:<24} limit={limit:<5} offered={sum(1 for r in rows if r['decision']=='offered'):<2} "
                f"trimmed={len(trimmed)} unanswerable={len(unanswerable)} missing={sum(1 for r in rows if r['decision']=='missing')}"
            )
            if unanswerable:
                unanswerable_fields.append(f"{name} (limit {limit})")
        # Appended unconditionally, so the report always carries the same six
        # findings in the same severity order. `what` says whether it was seen.
        findings.append(
            {
                "key": "url_vs_maxlength",
                "severity": "medium",
                "order": 6,
                "status": (
                    "open - not fixed in this round; recorded as a design question"
                    if unanswerable_fields
                    else "not observed in this run"
                ),
                "what": (
                    "form_04: a short character limit meets an unbreakable token and the assistant reports "
                    "the field as unanswerable instead of shortening a URL - which it could do without "
                    "inventing anything"
                    + (
                        f" (seen on {', '.join(unanswerable_fields)})"
                        if unanswerable_fields
                        else " (no such field in this run)"
                    )
                ),
                "kind": "edge",
                "evidence": (
                    "round records, message kind `length_unanswerable`. Not fixed in this round; recorded "
                    "as a design question - a URL-aware `fit_to_length` would change "
                    "`server/services.fit_to_length`, which is the pipeline's decision, not this matrix's."
                ),
            }
        )

        # form_05: the traps
        prefilled = rows_for("form_05_traps", "full_name")
        report.check(
            bool(prefilled) and all(row["decision"] == "already_filled" for row in prefilled),
            "form_05: the page-side pre-fill is reported already_filled and never overwritten",
        )
        readonly = rows_for("form_05_traps", "email_readonly")
        readonly_offered = [row for row in readonly if row["decision"] == "offered"]
        readonly_decisions = sorted({row["decision"] for row in readonly})
        report.check(bool(readonly), "form_05: the readonly control was scanned")
        # M2, report section 5 row 2 - asserted at the level the report counts, and at
        # the level the brief asked for: decision `not_fillable`, no value behind it.
        report.equal(
            readonly_decisions,
            [ROUND3_EXPECTED["email_readonly_decision"]],
            "form_05: the readonly control is not_fillable (M2)",
        )
        report.check(
            all(row["value_hash"] == "" for row in readonly),
            "form_05: the readonly control carries no value hash (M2)",
        )
        findings.append(
            {
                "key": "readonly_offered",
                "severity": "medium",
                "order": 2,
                "status": "fixed in round 2",
                "what": (
                    "form_05: the `readonly` control was treated as fillable and offered a value - nothing "
                    "in the skip table or the content script's fillable test knew about readonly "
                    f"({len(readonly)} run(s), every one `offered` in round 1). **Round 2:** `readonly` is "
                    "refused at the page (never read, never written) and in `field_map.SKIPPED_ATTRIBUTES`, "
                    "so the control is `not_fillable` with no value."
                ),
                "kind": "edge",
                "evidence": (
                    "round-1 records: field `email_readonly`, decision `offered`; round-2 records: decision "
                    "`not_fillable`, `value_hash` empty; regression "
                    "`tests/test_form_matrix_regressions.py::test_readonly_control_is_not_fillable`; source "
                    "`server/field_map.SKIPPED_ATTRIBUTES` + `extension/src/content.ts:isReadonlyControl`"
                ),
            }
        )

        # M3, report section 5 row 3 - the `disabled` attribute, the same family as
        # `readonly`. Asserted at the level the report counts, plus the property
        # that makes the refusal meaningful: no value behind it. The control is an
        # `input`, so nothing *except* the new attribute check would have stopped
        # it - which is exactly why the round-2 `readonly` finding recurred here.
        disabled = rows_for("form_05_traps", "email_disabled")
        disabled_offered = [row for row in disabled if row["decision"] == "offered"]
        disabled_decisions = sorted({row["decision"] for row in disabled})
        report.check(bool(disabled), "form_05: the disabled control was scanned")
        report.equal(
            disabled_decisions,
            [ROUND3_EXPECTED["email_disabled_decision"]],
            "form_05: the disabled control is not_fillable (M3)",
        )
        report.check(
            all(row["value_hash"] == "" for row in disabled),
            "form_05: the disabled control carries no value hash (M3)",
        )
        report.check(
            not disabled_offered,
            "form_05: no run offers a value into the disabled control (M3)",
        )
        findings.append(
            {
                "key": "disabled_control",
                "severity": "medium",
                "order": 3,
                "status": "fixed in round 3",
                "what": (
                    "form_05: a `disabled` control was treated as fillable, exactly as `readonly` had "
                    "been. A disabled input is still scanned, and nothing in the skip table or in the "
                    "content script's fillable test knew about the attribute, so the assistant would "
                    "offer a value the page can neither edit nor submit. It is the same *family* of "
                    "mistake round 2 fixed and not a new one, which is the point of listing it. "
                    "**Round 3:** `disabled` is refused at the page (never read, never written) and in "
                    "`field_map.SKIPPED_ATTRIBUTES` as a second line of defence; the page-side `type` "
                    "rules still win, so a `disabled` password field stays a type refusal."
                ),
                "kind": "edge",
                "evidence": (
                    "regression `tests/test_form_matrix_regressions.py::test_disabled_control_is_not_fillable`; "
                    f"records: field `email_disabled`, decision "
                    f"`{','.join(disabled_decisions) or 'absent'}`, `value_hash` empty; source "
                    "`server/field_map.SKIPPED_ATTRIBUTES` + `extension/src/content.ts:isDisabledControl`; "
                    "the control was added to `demo/form_matrix/form_05_traps.html` this round, so "
                    "rounds 1 and 2 record it as `absent` rather than as a pass"
                ),
            }
        )

        # M1, report section 5 row 4 (finding 7a). Round 2's L2 review found the
        # `experience` and `project` categories were "tailored", so their fact-shaped
        # sub-fields inherited the posting's retrieval score and were withheld on a
        # cross-domain posting even though the profile plainly states them. The check
        # follows the *category in the records*, not a hard-coded field id, so it stays
        # honest if the classifier's output changes.
        lc_primary = next((rec for rec in records if rec["run_id"] == LC_CROSS_DOMAIN_RUN), None)
        lc_fact_rows = [
            row
            for row in (lc_primary["per_field"] if lc_primary else [])
            if row.get("category") in {"experience_fact", "project_fact"}
        ]
        report.check(
            lc_primary is not None and bool(lc_fact_rows),
            "M1: the cross-domain run carries fact-shaped experience / project controls",
        )
        report.equal(
            sorted({row["decision"] for row in lc_fact_rows}),
            ["offered"],
            "M1: every fact-shaped experience / project control in the cross-domain run is offered (finding 7a)",
        )
        findings.append(
            {
                "key": "experience_fact_boundary",
                "severity": "medium",
                "order": 4,
                "status": "fixed in round 3",
                "what": (
                    "`services._evidence_for_field` treated the whole `experience` and `project` "
                    "categories as posting-tailored, so fact-shaped sub-fields inherited the posting's "
                    "retrieval score. On a cross-domain posting that score is 0.00 and `Company name` / "
                    "`Job title` / `Internship period` / `Project name` were withheld (`abstained`) even "
                    "though the profile states them; the very same fields were `offered` on the same form "
                    f"with an in-domain posting. In the cell where it showed up, "
                    f"{ROUND2_RECORDED['lc_form_01_abstained']} fields were withheld and four of them were "
                    "fact-shaped. **Round 3:** those four moved to `experience_fact` / `project_fact`, "
                    "which are fact categories, so they use the deterministic extraction confidence "
                    "instead of the retrieval score."
                ),
                "kind": "bug",
                "evidence": (
                    "regression `tests/test_form_matrix_regressions.py::test_experience_facts_are_not_tailored`; "
                    f"records: run `{LC_CROSS_DOMAIN_RUN}`, where `Company name` and `Job title` sat on "
                    "`internship.internship_employer` / `internship.internship_title` and were `abstained` "
                    "in round 2 and are `offered` now; round-2 L2 sheet question-set-2 rows 5 and 6 "
                    "(`wf_571f50676d64`, `wf_f551d6320a36`), both `disagree`; source "
                    "`server/field_map._FIELD_MAP` + `services.FACT_CATEGORIES`"
                ),
            }
        )

        # M2, report section 5 row 5 (finding 7b). The reason on a fact-shaped field
        # name the absent fact, not the retrieval component - nothing was ever
        # retrieved for such a field, so naming retrieval sends the user to fix the
        # posting instead of the profile. Rows are selected by category and decision,
        # both read from the records.
        no_fact_rows = [
            row
            for rec in records
            for row in rec["per_field"]
            if row.get("category") in {"education", "personal"}
            and row["decision"] == "missing"
            and row["reasons"]
        ]
        blamed_retrieval = [
            f"{row['name'] or row['field_id']}: {'; '.join(row['reasons'])}"
            for row in no_fact_rows
            if any("retrieval similarity" in reason for reason in row["reasons"])
        ]
        named_the_fact = [
            row
            for row in no_fact_rows
            if any("no fact in the authorised profile" in reason for reason in row["reasons"])
        ]
        report.check(
            bool(no_fact_rows),
            "M2: there is at least one fact-shaped field with no fact to check (finding 7b)",
        )
        report.equal(
            blamed_retrieval[:4],
            [],
            "M2: no fact-shaped field with no fact blames retrieval similarity (finding 7b)",
        )
        report.check(
            bool(named_the_fact),
            "M2: the missing reason names the absent fact instead (finding 7b)",
        )
        findings.append(
            {
                "key": "missing_reason_attribution",
                "severity": "medium",
                "order": 5,
                "status": "fixed in round 3",
                "what": (
                    "a fact-shaped control whose fact is absent from the profile was reported `missing` "
                    "with the reason `retrieval similarity 0.00 < threshold 0.40`, which sends the user to "
                    "fix the posting instead of the profile. Nothing had been retrieved for the field, so "
                    "the reason named a component that was never consulted. The outcome was right and the "
                    "explanation was wrong, which is why this is a report repair rather than a count "
                    "movement. **Round 3:** `services._evidence_for_field` returns no evidence at all for a "
                    "fact category with no fact, and the decision branch reports `no fact in the "
                    "authorised profile` instead."
                ),
                "kind": "bug",
                "evidence": (
                    "regression `tests/test_form_matrix_regressions.py::test_missing_reason_names_the_absent_fact`; "
                    "records: field `gpa`, category `education`, decision `missing`, reason names the absent "
                    "fact; round-2 L2 sheet question-set-2 row 4 (`wf_f263ef9b690a`) carried the note; source "
                    "`server/services._evidence_for_field` + `services.MSG_NO_FACT`. The round-2 note also "
                    "inferred, from `source = \"none\"`, that the control had never been classified as "
                    "`education`; the record above shows the category is `education`, so the fix is right for "
                    "a different reason than the note guessed. Both are stated rather than one being dropped."
                ),
            }
        )
        button_present = "confirm_application" in forms["form_05_traps"].html
        button_scanned = any(
            row["name"] == "confirm_application"
            for rec in records
            if rec["form_id"] == "form_05_traps"
            for row in rec["per_field"]
        )
        report.check(button_present, "form_05: the <button type=submit> is on the page")
        report.check(
            not button_scanned,
            "form_05: the <button type=submit> is not in the scan payload at all",
            "the scan selector matches input/textarea/select/contenteditable only",
        )
        findings.append(
            {
                "key": "button_not_scanned",
                "severity": "low",
                "order": 8,
                "status": "open - not fixed in this round; recorded as a design question",
                "what": (
                    "form_05: a `<button type=\"submit\">` is invisible to the scanner - the selector matches "
                    "`input` only - so the panel cannot report it as a refused control. It is also why it "
                    "cannot be clicked by the assistant, so the effect is a reporting gap, not a safety one"
                ),
                "kind": "edge",
                "evidence": "form_05 field inventory vs the scan payload: `confirm_application` absent",
            }
        )

        # form_06: the bilingual and Chinese-only controls
        huzhao = rows_for("form_06_bilingual", "huzhao")
        report.check(
            bool(huzhao) and all(row["sensitive"] for row in huzhao),
            "form_06: the Chinese-only '护照号码' control is detected as an identity document",
        )
        beizhu = rows_for("form_06_bilingual", "beizhu")
        report.check(
            bool(beizhu) and all(row["decision"] != "offered" for row in beizhu),
            "form_06: the Chinese-only '补充说明' control is not answered",
        )
        self_intro = rows_for("form_06_bilingual", "self_intro")
        report.check(
            bool(self_intro) and all(row["fillable"] for row in self_intro),
            "form_06: the contenteditable control is accepted (tag normalisation works)",
        )
        beizhu_answered = bool(beizhu) and any(row["decision"] == "offered" for row in beizhu)
        findings.append(
            {
                "key": "chinese_only_label",
                "severity": "medium",
                "order": 7,
                "status": "open - not fixed in this round; recorded as a design question",
                "what": (
                    "form_06: a label written only in Chinese is unclassifiable - `_FIELD_MAP` has no Chinese "
                    "patterns except in the identity-document block - so '补充说明' is reported missing while "
                    "its English twin would be answered"
                    + (" (it was answered in this run)" if beizhu_answered else "")
                ),
                "kind": "edge",
                "evidence": (
                    "round records, field `beizhu`, category `unknown`, decision `missing`. Adding Chinese "
                    "patterns to `_FIELD_MAP` is a classifier decision for the pipeline, not for this matrix."
                ),
            }
        )

        # L-D: the repeatability probe. M3, report section 5 row 3. It still runs
        # and its result is still asserted - the flow is kept - but it is reported
        # as *not testable* rather than as "no wobble was observed". The offline
        # stub is a literal extractor with no sampler, so identical repeats are a
        # property of the stub, not evidence that a live model would be stable.
        repeats = [rec for rec in records if rec["layer"] == "L-D"]
        ld_outcomes = 0
        if len(repeats) >= 2:
            signature = [
                json.dumps(
                    [[row["field_id"], row["decision"], row["value_hash"]] for row in rec["per_field"]],
                    sort_keys=True,
                )
                for rec in repeats
            ]
            ld_outcomes = len(set(signature))
            report.check(
                len(set(signature)) == 1,
                "L-D: the repeats agree field by field (structurally expected offline)",
                f"{len(set(signature))} distinct outcomes",
            )
        run_mode = records[0]["mode"] if records else ""
        if run_mode == "offline_stub":
            print("  L-D is structurally deterministic in offline mode; see section 6.")
        findings.append(
            {
                "key": "ld_not_testable",
                "severity": "low",
                "order": 9,
                "status": (
                    "not testable in offline mode" if run_mode == "offline_stub" else "measured"
                ),
                "what": (
                    f"L-D: **not testable in offline mode.** The same cell was run {len(repeats)} time(s) and "
                    f"produced {ld_outcomes} distinct outcome(s) - but the offline stub is a literal "
                    "extractor: it has no sampler, so any repetition must agree. This is a property of the "
                    "stub, not evidence that a live model would be stable."
                ),
                "kind": "edge",
                "evidence": (
                    "run records for L-D compared on (field_id, decision, value_hash). Stability requires "
                    "`mode=live_api`; it is not claimed by this matrix - see section 6."
                ),
            }
        )

        # --------------------------------------------------- change log (3 rounds)
        report.section("5b. Change log - three rounds")

        # The after-column is derived, not typed: the same function that derives the
        # two historical columns, applied to this run's records. The recorded round-3
        # expectations are then asserted against it, key by key, so a fix that
        # overshot or undershot fails here instead of being reported as a success.
        after_values = aggregate_records(records)
        report.equal(
            sorted(set(ROUND3_EXPECTED) - set(after_values)),
            [],
            "every change-log row has a measured after value",
        )
        for key, expected in ROUND3_EXPECTED.items():
            report.equal(
                after_values.get(key),
                expected,
                f"round 3 moved {key} to {expected!r} (recorded, not adjusted)",
            )

        # The two historical columns are recomputed from the snapshots this round
        # deliberately wrote to disk *before* touching anything, so a number in the
        # change log is checkable rather than a transcription. A missing snapshot
        # fails the check instead of silently degrading to "no check".
        for snapshot, recorded, label in (
            ("runs_before_round2.jsonl", ROUND1_RECORDED, "round 1"),
            ("runs_before_round3.jsonl", ROUND2_RECORDED, "round 2"),
        ):
            previous = read_snapshot(out_dir / snapshot)
            if previous is None:
                report.check(False, f"the {label} snapshot {snapshot} is on disk")
                continue
            derived_history = aggregate_records(previous)
            mismatched = [
                f"{key}: recorded {expected!r} / derived {derived_history.get(key)!r}"
                for key, expected in recorded.items()
                if derived_history.get(key) != expected
            ]
            report.equal(
                mismatched,
                [],
                f"the recorded {label} column matches its snapshot, key by key",
            )

        # A change-log row without a round-3 column would print `absent` and read
        # like a movement, so the two key sets are required to agree.
        report.equal(
            sorted({key for _label, key, _why in CHANGE_ROWS} - set(ROUND3_EXPECTED)),
            [],
            "every change-log row has a round-3 column",
        )
        change_log = {
            "round1": ROUND1_RECORDED,
            "round2": ROUND2_RECORDED,
            "round3": after_values,
        }
        print(
            "  change log: offered "
            f"{ROUND1_RECORDED['offered']} -> {ROUND2_RECORDED['offered']} -> "
            f"{after_values['offered']}; abstained "
            f"{ROUND1_RECORDED['abstained']} -> {ROUND2_RECORDED['abstained']} -> "
            f"{after_values['abstained']}; not_fillable "
            f"{ROUND1_RECORDED['not_fillable']} -> {ROUND2_RECORDED['not_fillable']} -> "
            f"{after_values['not_fillable']}"
        )
        print(
            "  the brief's round-2 prediction of `form_03 missing` 7 -> 6 cannot hold: the form's "
            "field total is fixed and only `missing` is available, so offered 17 -> 16 forces "
            "missing 7 -> 8. The records are shown as they are."
        )

        # ------------------------------------------------------------- H3
        report.section("6. H3 - the plaintext scan")
        runs_path = out_dir / "runs.jsonl"
        l2_path = out_dir / "l2_review.md"
        fingerprint_path = out_dir / "source_fingerprint.json"

        sentinels = build_sentinels(resumes_list, jds_list)
        report.check(len(sentinels) >= 20, f"the sentinel set is non-trivial ({len(sentinels)} strings)")

        # Write the record file first, redacted by construction, then prove it.
        with runs_path.open("w", encoding="utf-8") as fh:
            for rec in records:
                fh.write(redact(json.dumps(rec, ensure_ascii=False), sentinels) + "\n")
        fingerprint_path.write_text(
            json.dumps(fingerprint, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

        # The L2 sheet is hand-filled once and must survive later runs: a reviewer's
        # verdicts are evidence, and two section 5 rows are built from them. So when
        # the real sheet already carries verdicts, the generated sheet goes to a
        # sibling name and the privacy scan follows whichever file was written.
        l2_text = render_l2(records, resumes)
        existing_l2 = l2_path.read_text(encoding="utf-8") if l2_path.exists() else ""
        if has_hand_verdicts(existing_l2):
            l2_written = out_dir / "l2_review.generated.md"
            print(
                f"  {l2_path.name} carries hand verdicts {l2_verdict_counts(existing_l2)} - "
                f"left alone; the fresh sheet went to {l2_written.name}"
            )
        else:
            l2_written = l2_path
        l2_written.write_text(redact(l2_text, sentinels), encoding="utf-8")

        action_log = ARTIFACTS / "agent_actions.jsonl"
        report.check(
            not action_log.exists(),
            "the server's optional action log was never created (RJD_SERVER_LOG stayed off)",
            str(action_log),
        )

        artifact_scan = scan_for_sentinels(
            [runs_path, l2_written, fingerprint_path], sentinels
        )
        report.equal(artifact_scan["hits"], [], "no source text appears in any written artifact")
        tmp_scan = scan_directory_for_sentinels(tmp_dir, sentinels)
        report.equal(tmp_scan["hits"], [], "no source text appears anywhere in the run's temp directory")
        report.check(
            all(needle not in runs_path.read_text(encoding="utf-8") for needle in sentinels),
            "runs.jsonl holds hashes and lengths only",
        )
        print(
            f"  scanned {artifact_scan['files_scanned']} artifact file(s) and "
            f"{tmp_scan['files_scanned']} temp file(s) against {len(sentinels)} sentinel(s)"
        )
        print("  chrome.storage.local: NOT scanned - it exists only inside a browser extension")
        print("  context. The manual checklist covers it. This is a known gap, not a pass.")

        h3 = {
            "sentinels": len(sentinels),
            "artifact_files_scanned": artifact_scan["files_scanned"],
            "artifact_hits": artifact_scan["hits"],
            "temp_files_scanned": tmp_scan["files_scanned"],
            "temp_hits": tmp_scan["hits"],
            "action_log_created": action_log.exists(),
            "chrome_storage_local": "not_scanned_outside_a_browser",
            "temp_dir": str(tmp_dir),
        }
        (out_dir / "privacy_scan.json").write_text(
            json.dumps(h3, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

        # ------------------------------------------------------------- H7
        report.section("7. H7 - policy files unchanged")
        report.equal(fingerprint["abstention_threshold"], 0.4, "the abstention threshold is still 0.4")
        report.equal(
            fingerprint["corpus_recalibrated_for_this_matrix"], False,
            "no recalibration was run for this matrix",
        )
        report.check(
            all(digest != "MISSING" for digest in fingerprint["files"].values()),
            "every policy file was found and hashed",
        )

        # ------------------------------------------------------------- H8
        report.section("8. H8 - timing metrics")
        print("  H8: no duration is measured or reported by this script or its report")

        # ------------------------------------- round-2 inputs for the report
        # Section 1 and section 2.3 both lead with a series rather than a single
        # count, and both are derived here from `records` - never typed in.
        abstained_rows = [
            row for rec in records for row in rec["per_field"] if row["decision"] == "abstained"
        ]
        abstention = {
            "fields": len(abstained_rows),
            "runs": sum(1 for rec in records if rec["counts"]["abstained"]),
            "categories": sorted({row.get("category") or "unknown" for row in abstained_rows}),
        }
        profile_missing = [
            sum(
                1
                for rec in records
                if rec["layer"] == "L-B" and rec["resume_id"] == resume_id
                for row in rec["per_field"]
                if row["decision"] == "missing"
            )
            for resume_id in ("full_profile", "sparse_profile", "minimal_profile")
        ]
        # Section 1 claims abstention never lands on a personal or education
        # fact, and section 2.3 claims `missing` rises monotonically with profile
        # sparsity. Both are checkable against the records, so both are checked
        # here rather than asserted in prose (report.md sections 1 and 2.3).
        from server.services import TAILORED_CATEGORIES

        stray_categories = sorted(set(abstention["categories"]) - set(TAILORED_CATEGORIES))
        report.equal(
            stray_categories,
            [],
            "section 1: every abstention is on a posting-tailored field, none on a personal fact",
        )
        report.check(
            all(a < b for a, b in zip(profile_missing, profile_missing[1:])),
            f"section 2.3: `missing` rises with profile sparsity {profile_missing} (S1)",
        )

        # Section 7, the live spot-check (O1). It is opt-in because every cell is
        # a paid call. When it is not run the report renders the *deferral*, so
        # the offline zero-fabrication figure stays labelled structurally trivial
        # instead of being quietly upgraded to evidence.
        live_result: dict[str, Any] = {
            "status": "deferred",
            "reason": (
                "not run this round. The two cells need `mode=live_api` and a paid call each, so "
                "they were left unrun rather than run silently - the offline zero-fabrication "
                "figure therefore stays structurally trivial, not earned"
            ),
        }

        # ------------------------------------------------------------ report
        report.section("9. Report")
        checks_summary = {
            "h2": len(posts) == 0,
            "h2_detail": f"{len(posts)} POST in the access log, 0 values offered for submit-shaped controls",
            "h3": not artifact_scan["hits"] and not tmp_scan["hits"] and not action_log.exists(),
            "h3_detail": (
                f"{artifact_scan['files_scanned'] + tmp_scan['files_scanned']} file(s) scanned, "
                f"{len(artifact_scan['hits']) + len(tmp_scan['hits'])} hit(s); "
                "chrome.storage.local out of reach of a non-browser check"
            ),
            "h5": all(not rec["invariants"]["identity_doc_echoed"] for rec in records)
            and all(row["value_hash"] == "" for row in sensitive_rows),
            "h5_detail": (
                f"{len(sensitive_rows)} identity control(s) across the matrix, all sensitive_skipped "
                "with no value; canary absent from every response"
            ),
            "h6": all(_h6_holds(rec) for rec in records),
            "h6_detail": "every missing/abstained/sensitive field has suggested_value = null",
            "access_log_posts": len(posts),
            "access_log_gets": len(gets),
            "machine_summary": f"{report.passed} L1 check(s) passed before the report",
        }
        report_text = render_report(
            records=records,
            resumes=resumes,
            forms=forms,
            checks=checks_summary,
            l2_text=l2_text,
            h3=h3,
            fingerprint=fingerprint,
            findings=findings,
            total_checks=report.passed,
            change_log=change_log,
            abstention=abstention,
            profile_missing=profile_missing,
            live=live_result,
        )
        # A renderer that silently returned nothing used to surface three lines
        # later as a TypeError from `redact`, nowhere near the cause. Name it here
        # instead, so the failure says what actually went wrong.
        report.check(
            bool(report_text and report_text.strip()),
            "the report renderer produced a body",
        )
        report_text = redact(report_text, sentinels)
        leaked = [needle for needle in sentinels if needle in report_text]
        report.equal(leaked, [], "the rendered report contains no source text")
        (out_dir / "report.md").write_text(report_text, encoding="utf-8")
        print(f"  wrote {out_dir / 'report.md'}")

    finally:
        client.close()
        backend_server.should_exit = True
        httpd.shutdown()
        kb_provider.close()
        time.sleep(0.3)

    # ------------------------------------------------------------- summary
    print("\n" + "=" * 74)
    total = report.passed + len(report.failures)
    print(f"RESULT: {report.passed}/{total} checks passed")
    if report.failures:
        print("\nFailures:")
        for item in report.failures:
            print(f"  - {item}")
    print("=" * 74)
    print(
        "\nScope, stated plainly: this matrix drove the assistant's HTTP contract over six\n"
        "simulated forms, five synthetic resumes and three synthetic postings, in offline\n"
        "mode. It is a wiring, guard and consistency check. It is not evidence about the\n"
        "quality of a live model's answers, it is not a browser run, and no timing metric\n"
        "was enabled. See artifacts/form_matrix/report.md sections 5 and 6."
    )
    return 0 if not report.failures else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
