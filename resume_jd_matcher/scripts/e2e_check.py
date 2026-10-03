"""End-to-end check: demo page -> server -> suggestions -> controlled fill.

This runs the whole browser-assistant path against a real HTTP server on
127.0.0.1, driven by the *actual* demo page rather than by hand-written JSON. If
this passes, the pieces are wired together; it is not evidence about answer
quality, and it says so at the end.

What it does, in order:

    1. parse `demo/application_form.html` the way the content script does
    2. start the backend on a loopback port with a token, in offline mode
    3. `/health` unauthenticated; `/generate` rejected without a token
    4. `/scan` - field classification, sensitive detection, no value echo
    5. `/jd/analyze` - posting analysis
    6. `/generate` condition C - suggestions, counts, privacy echo
    7. apply the suggestions to the parsed document, then assert the invariants
       that no browser is needed to check: nothing was written into a sensitive
       field, a hidden field, a file picker, a password box, or a submit control
    8. the no-submit invariant, on both sides of the wire, statically

Design note, stated rather than hidden: step 1 re-implements the content
script's DOM extraction in Python. It is deliberately an approximation of
`extension/src/content.ts` - it resolves labels from `label[for]` / `aria-label`
/ wrapping `label`, reads `maxlength` and `select` options, and honours the same
skip rules. The content script itself is verified by `tsc --noEmit`, by
`vite build` (which asserts it is still a classic script with no `import`), and
by `scripts/ui_headless_check.py`. Keeping the extraction here means this script
can run on a machine with no browser at all.

Round 2: step 1's mirror gained the two rules the form-matrix round-2 report
found missing. Section text (`<legend>`, a heading, a `<caption>`) is *context*
and may never name a field; and a `readonly` control is neither read nor
written. See `artifacts/form_matrix/report.md` sections 5 #1 and 5 #3. The
bundle assertion below changed with them - it now requires the section-level
helper and `section_context` to be *present* in `dist/content.js`, instead of
requiring the word `legend` to be absent.

Round 3 added the third member of that family: a `disabled` control. It is the
same decision one step further out (report.md section 6), so the mirror gained
`_is_disabled`, the payload gained a `disabled` key, and the bundle assertion now
also requires `isDisabledControl` to be present.

Usage:
    python scripts/e2e_check.py            # exit 0 = every check passed
    python scripts/e2e_check.py --verbose
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import threading
import time
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

DEMO_PAGE = REPO_ROOT / "demo" / "application_form.html"
EXTENSION_DIST = REPO_ROOT / "extension" / "dist"

TOKEN = "e2e-check-token"
JD_TEXT = (
    "Machine Learning Intern - Acme Corp, Singapore\n"
    "We are looking for a graduate intern to join our applied research team.\n"
    "Requirements: Python, PyTorch, SQL and a strong grounding in statistics.\n"
    "Nice to have: Docker, Kubernetes, experience with retrieval systems.\n"
    "You will build training pipelines, evaluate models and present results."
)

PROFILE: dict[str, Any] = {
    "personal_info": {
        "full_name": "Zhang Wei",
        "email": "zhang.wei@example.edu",
        "phone": "+65 9123 4567",
        "location": "Singapore",
        "linkedin": "linkedin.com/in/zhangwei",
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

#: The document number deliberately present on the demo page. It must not appear
#: in any response body.
PASSPORT_ON_PAGE = "E12345678"

SKIP_INPUT_TYPES = {"hidden"}

#: Mirrors `content.ts:NEVER_READ_TYPES`. Type-based only; the two attribute-based
#: refusals (`readonly`, `disabled`) are predicates below and join this condition in
#: `extract_fields`. These controls are reported - the panel
#: has to be able to say why it leaves them alone - but their value is never read,
#: because a password is a secret and a file input holds a browser-managed fake
#: path. Neither is ever filled, so reading them would move a secret across the
#: loopback boundary for nothing.
NEVER_READ_TYPES = {"password", "file"}


# --------------------------------------------------------------------------- #
# Tiny check harness
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
# 1. Parse the demo page the way the content script does
# --------------------------------------------------------------------------- #


def _text(node: Any) -> str:
    return " ".join((node.get_text(" ") or "").split()) if node is not None else ""


def _is_section_level(element: Any) -> bool:
    """Mirrors `content.ts:isSectionLevelText`.

    A section heading names the block, not the field. It is reported to the
    server as `section_context` and may never become a field's label - that is
    the round-2 fix for report.md section 5 row 1.
    """
    tag = (element.name or "").lower()
    if tag in {"legend", "caption"}:
        return True
    if tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
        return True
    return element.get("role") == "heading"


def _is_readonly(element: Any) -> bool:
    """Mirrors `content.ts:isReadonlyControl` - readonly is an attribute, not a type."""
    if (element.name or "").lower() not in {"input", "textarea"}:
        return False
    return element.has_attr("readonly")


def _is_disabled(element: Any) -> bool:
    """Mirrors `content.ts:isDisabledControl`.

    Same family as `readonly`: the control is still reported, its value is never
    read, and the server refuses to fill it. `disabled` is valid on a `<select>`
    as well, so this predicate is one tag wider. Round 3, report.md section 6.
    """
    if (element.name or "").lower() not in {"input", "textarea", "select"}:
        return False
    return element.has_attr("disabled")


def _resolve_section_context(element: Any) -> str:
    """Mirrors `content.ts:resolveSectionContext`. Context, never a name."""
    fieldset = element.find_parent("fieldset")
    if fieldset is not None:
        text = _text(fieldset.find("legend"))
        if text:
            return text[:200]
    return ""


def _resolve_label(soup: Any, element: Any) -> str:
    element_id = element.get("id")
    if element_id:
        explicit = soup.find("label", attrs={"for": element_id})
        if explicit and _text(explicit):
            return _text(explicit)[:200]
    aria = (element.get("aria-label") or "").strip()
    if aria:
        return aria[:200]
    wrapping = element.find_parent("label")
    if wrapping is not None:
        clone_text = _text(wrapping)
        own = element.get("value") or ""
        if own:
            clone_text = clone_text.replace(own, " ").strip()
        clone_text = " ".join(clone_text.split())
        if clone_text:
            return clone_text[:200]
    previous = element.find_previous_sibling()
    # Section-level text (a <legend>, a heading, a <caption>) may not name a
    # field. Round 2, report.md section 5 row 1 - mirrors `content.ts`.
    if previous is not None and not _is_section_level(previous):
        text = _text(previous)
        if text and len(text) <= 200:
            return text
    return ""


def _resolve_help_text(element: Any) -> str:
    # Mirrors `content.ts`: a <fieldset><legend> is section-level text and is
    # deliberately excluded, because the server classifies a field by its label
    # plus its help text and a section heading would leak into every field in it.
    title = (element.get("title") or "").strip()
    if title:
        return title[:180]
    nxt = element.find_next_sibling()
    if nxt is not None and nxt.name not in {"input", "select", "textarea", "button"}:
        text = _text(nxt)
        if text and len(text) <= 180:
            return text
    return ""


def _resolve_options(soup: Any, element: Any) -> list[str]:
    if element.name == "select":
        return [(_text(option)) for option in element.find_all("option") if _text(option)][:40]
    if element.name == "input" and (element.get("type") or "").lower() in {"radio", "checkbox"}:
        name = element.get("name")
        if not name:
            label = _resolve_label(soup, element)
            return [label] if label else []
        group = soup.find_all("input", attrs={"type": element.get("type"), "name": name})
        return [
            (_resolve_label(soup, item) or (item.get("value") or "")) for item in group
        ][:40]
    return []


def _build_selector(soup: Any, element: Any) -> str:
    element_id = element.get("id")
    if element_id:
        return f"#{element_id}"
    name = element.get("name")
    if name:
        return f'{element.name}[name="{name}"]'
    return element.name


def _current_value(element: Any) -> str:
    if element.name in {"select", "textarea"}:
        if element.name == "select":
            selected = element.find("option", selected=True)
            return _text(selected) if selected is not None else ""
        return element.get_text() or ""
    kind = (element.get("type") or "text").lower()
    if kind in {"radio", "checkbox"}:
        return (element.get("value") or "checked") if element.has_attr("checked") else ""
    return element.get("value") or ""


def extract_fields(html: str) -> list[dict[str, Any]]:
    """Approximate `content.ts:scanPage` with BeautifulSoup. See the module docstring."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    out: list[dict[str, Any]] = []
    seen: set[int] = set()

    for element in soup.select(
        'input, textarea, select, [contenteditable="true"], [contenteditable=""], [role="textbox"]'
    ):
        if id(element) in seen:
            continue
        seen.add(id(element))
        if element.has_attr("hidden") or element.get("aria-hidden") == "true":
            continue
        kind = ((element.get("type") or "text") if element.name == "input" else element.name).lower()
        if element.name == "input" and kind in SKIP_INPUT_TYPES:
            # Hidden inputs are excluded from the scan by the content script. They
            # are still worth asserting about, so one is added explicitly below.
            continue

        max_length = None
        raw_max = element.get("maxlength")
        if raw_max and str(raw_max).isdigit():
            max_length = int(raw_max)

        out.append(
            {
                "tag": element.name,
                "type": kind,
                "name": element.get("name") or "",
                "id": element.get("id") or "",
                "label": _resolve_label(soup, element),
                "placeholder": element.get("placeholder") or "",
                "aria_label": element.get("aria-label") or "",
                "required": element.has_attr("required") or element.get("aria-required") == "true",
                "max_length": max_length,
                "options": _resolve_options(soup, element),
                "help_text": _resolve_help_text(element),
                # A locked or disabled control is reported but never read - same
                # rule as a password, and the server refuses to fill it either way.
                "current_value": ""
                if kind in NEVER_READ_TYPES or _is_readonly(element) or _is_disabled(element)
                else _current_value(element),
                "selector": _build_selector(soup, element),
                "readonly": _is_readonly(element),
                "disabled": _is_disabled(element),
                "section_context": _resolve_section_context(element),
            }
        )

    # The content script skips hidden inputs, but the server's own refusal is part
    # of the contract, so the demo page's CSRF token is included here on purpose.
    csrf = soup.find("input", attrs={"type": "hidden"})
    if csrf is not None:
        out.insert(
            0,
            {
                "tag": "input",
                "type": "hidden",
                "name": csrf.get("name") or "",
                "id": csrf.get("id") or "",
                "label": "",
                "placeholder": "",
                "aria_label": "",
                "required": False,
                "max_length": None,
                "options": [],
                "help_text": "",
                "current_value": csrf.get("value") or "",
                "selector": f'#{csrf.get("id")}',
                "readonly": False,
                "disabled": False,
                "section_context": "",
            },
        )
    return out


# --------------------------------------------------------------------------- #
# 2. Start the backend for real
# --------------------------------------------------------------------------- #


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def start_server(port: int):
    """Run the real ASGI app on 127.0.0.1 in a background thread."""
    import uvicorn

    from server.app import create_app

    app = create_app(require_token=True, token=TOKEN)
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", lifespan="on")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    deadline = time.time() + 30
    while time.time() < deadline:
        if getattr(server, "started", False):
            return server
        if not thread.is_alive():
            raise RuntimeError("the server thread died before it started")
        time.sleep(0.05)
    raise RuntimeError("the server did not start within 30s")


# --------------------------------------------------------------------------- #
# 3. The run
# --------------------------------------------------------------------------- #


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verbose", action="store_true", help="print every passing check")
    args = parser.parse_args(argv)

    # Offline, so the script needs no API key and is deterministic. The mode is
    # asserted below and named in the summary: this validates wiring, not quality.
    os.environ["RJD_OFFLINE"] = "1"
    os.environ.pop("RJD_SERVER_LOG", None)

    report = Report(verbose=args.verbose)
    import httpx

    print("=" * 72)
    print("End-to-end check: demo application form -> local backend")
    print("=" * 72)

    if not DEMO_PAGE.exists():
        print(f"FAIL: {DEMO_PAGE} not found")
        return 2
    html = DEMO_PAGE.read_text(encoding="utf-8")
    fields = extract_fields(html)

    report.section("0. Demo page and extension build")
    report.check(bool(fields), "the demo page yields fields to scan")
    report.check(
        any(f["type"] == "submit" for f in fields),
        "the demo page's submit control is inside the scan selector",
        "an <input type=submit> is scanned and refused; a <button> is never scanned at all",
    )
    report.check(
        any("passport" in (f["label"] or "").lower() for f in fields),
        "the demo page has a passport field (the assistant must refuse it)",
    )
    report.check(
        "preventDefault" in html,
        "the demo page's submit handler calls preventDefault (it never posts anywhere)",
    )
    # A password box and a file picker are reported - the panel must be able to
    # explain why it leaves them alone - but their value is never read. Asserted
    # on a snippet rather than on the demo page, whose password box is empty in
    # the markup: an empty field would pass this test even if the rule were gone.
    secret_fields = extract_fields(
        '<form><input type="password" name="pw" value="hunter2">'
        '<input type="file" name="cv" value="hunter2"></form>'
    )
    report.check(
        len(secret_fields) == 2 and all(f["current_value"] == "" for f in secret_fields),
        "a password or file control is reported but its value is never read",
        f"got {[f['current_value'] for f in secret_fields]}",
    )
    content_js = EXTENSION_DIST / "content.js"
    if content_js.exists():
        bundle = content_js.read_text(encoding="utf-8")
        report.check(
            not any(line.strip().startswith(("import ", "export ")) for line in bundle.splitlines()),
            "dist/content.js is still a classic script (no import/export)",
        )
        for forbidden, why in [
            (".submit(", "form submission"),
            ("requestSubmit", "form submission"),
            ("new SubmitEvent", "form submission"),
        ]:
            report.check(forbidden not in bundle, f"the content script has no {why} call ({forbidden})")
        # Round 2 (report.md section 5 row 1). The old assertion was
        # `"legend" not in bundle`, which encoded "section text must not reach
        # the classifier" at a time when the only route was `help_text`. The
        # legend is now read deliberately, as `section_context`, and the rule is
        # enforced where it belongs: the section may *veto* an ambiguous name but
        # may never *be* a field's name. That half is pinned by
        # `tests/test_form_matrix_regressions.py::test_legend_never_names_a_field`.
        report.check(
            "isSectionLevelText" in bundle
            and "section_context" in bundle
            and "isDisabledControl" in bundle,
            "the content script still separates section text from a field's name "
            "(the legend is context, never a label)",
        )
        report.check(
            "NEVER_READ_TYPES" in bundle,
            "the built content script still carries the never-read list",
        )
        manifest = EXTENSION_DIST / "manifest.json"
        report.check(manifest.exists(), "the extension manifest is in dist/")
        if manifest.exists():
            data = json.loads(manifest.read_text(encoding="utf-8"))
            report.equal(data.get("manifest_version"), 3, "the manifest is Manifest V3")
    else:
        report.check(False, "extension/dist/content.js exists", "run `npm run build` in extension/")

    port = free_port()
    base = f"http://127.0.0.1:{port}"
    print(f"\n[server] starting on {base} (token required, offline mode)")
    server = start_server(port)
    client = httpx.Client(base_url=base, timeout=30.0, headers={"X-RJD-Token": TOKEN})

    try:
        # ------------------------------------------------------------------ health
        report.section("1. /health (unauthenticated, no user data)")
        health = client.get("/health")
        report.equal(health.status_code, 200, "/health answers without a token")
        payload = health.json()
        report.equal(payload.get("status"), "ok", "/health reports status ok")
        report.equal(payload.get("auth_required"), True, "/health says a token is required")
        report.equal(payload.get("mode"), "offline_stub", "/health reports the offline mode honestly")
        report.equal(payload.get("bind_host"), "127.0.0.1", "/health reports a loopback bind")
        report.check(
            payload.get("privacy", {}).get("in_memory_only") is True,
            "/health declares in-memory-only processing",
        )
        report.check(
            not payload.get("privacy", {}).get("action_log_enabled"),
            "the fingerprinted action log is off by default",
        )
        report.check(
            len(payload.get("sensitive_policy", {}).get("never_generated", [])) >= 5,
            "/health lists the never-generated document types",
        )
        report.check(TOKEN not in health.text, "/health does not echo the token")

        # ------------------------------------------------------------------ auth
        report.section("2. Authentication is enforced before any work")
        unauth = httpx.post(f"{base}/scan", json={"url": "", "page_title": "", "fields": []}, timeout=10)
        report.equal(unauth.status_code, 401, "/scan without a token is rejected")
        unauth_gen = httpx.post(
            f"{base}/generate",
            json={"fields": fields, "authorised_modules": ["personal_info"], "profile": PROFILE},
            timeout=10,
        )
        report.equal(unauth_gen.status_code, 401, "/generate without a token is rejected")

        # ------------------------------------------------------------------ scan
        report.section("3. /scan - classification and sensitive detection")
        scan = client.post(
            "/scan",
            json={"url": "file://demo/application_form.html", "page_title": "Graduate Programme Application", "fields": fields},
        )
        report.equal(scan.status_code, 200, "/scan answers")
        scanned = scan.json()
        counts = scanned["counts"]
        report.check(counts["total"] == len(fields), "every submitted control is reported back")
        report.check(counts["sensitive"] >= 2, f"both document fields are found (got {counts['sensitive']})")
        # hidden csrf + submit + reset + file + password = 5 refusals at least.
        report.check(counts["skipped"] >= 5, f"hidden/submit/reset/file/password are all skipped (got {counts['skipped']})")
        report.check(counts["fillable"] + counts["skipped"] == counts["total"], "fillable + skipped = total")
        report.check(
            not any(n in scan.text for n in [PASSPORT_ON_PAGE]),
            "the passport number on the page is not echoed by /scan",
        )

        def scanned_row(*, label: str = "", name: str = "", kind: str = "") -> dict[str, Any] | None:
            for row in scanned["fields"]:
                if label and row.get("label") == label:
                    return row
                if name and row.get("name") == name:
                    return row
                if kind and row.get("type") == kind:
                    return row
            return None

        by_label = {row["label"]: row for row in scanned["fields"]}
        for label, expected_fact in [
            ("Full name", "full_name"),
            ("Email address", "email"),
            ("Phone", "phone"),
            ("Current city", "location"),
            ("University / institution", "education_school"),
            ("Degree", "education_degree"),
            ("Company name", "internship_employer"),
            ("Job title", "internship_title"),
            ("Project name", "project_name"),
            ("Key skills", "top_skills"),
        ]:
            row = by_label.get(label)
            report.check(
                row is not None and row.get("fact_key") == expected_fact,
                f"{label!r} maps to {expected_fact}",
                f"got {row.get('fact_key') if row else 'no such field'}",
            )
        for label in ["Why do you want this role?", "Cover letter", "Additional information"]:
            row = by_label.get(label)
            report.check(
                row is not None and row.get("category") == "narrative",
                f"{label!r} is classified as narrative",
                f"got {row.get('category') if row else 'no such field'}",
            )
        report.check(
            (by_label.get("Passport number") or {}).get("sensitive") is True,
            "the passport field is marked sensitive by the server",
        )
        report.check(
            (by_label.get("NRIC / national ID number") or {}).get("sensitive") is True,
            "the NRIC field is marked sensitive by the server",
        )
        submit_row = scanned_row(kind="submit")
        report.check(submit_row is not None, "the submit control was scanned")
        if submit_row is not None:
            report.check(submit_row["fillable"] is False, "the submit control is not fillable")
            report.check("never submits" in submit_row["skip_reason"], "the submit control says why it is refused")
        reset_row = scanned_row(kind="reset")
        if reset_row is not None:
            report.check(reset_row["fillable"] is False, "the reset control is not fillable")
        file_row = scanned_row(kind="file")
        if file_row is not None:
            report.check(file_row["fillable"] is False, "the file picker is not fillable")
        password_row = scanned_row(kind="password")
        if password_row is not None:
            report.check(password_row["fillable"] is False, "the password box is not fillable")
        hidden_row = scanned_row(kind="hidden")
        if hidden_row is not None:
            report.check(hidden_row["fillable"] is False, "the hidden CSRF input is not fillable")

        # -------------------------------------------------------------- jd/analyze
        report.section("4. /jd/analyze")
        analyse = client.post(
            "/jd/analyze",
            json={
                "jd_text": JD_TEXT,
                "authorised_modules": ["personal_info", "education", "internship", "projects"],
                "profile": PROFILE,
                "condition": "B",
            },
        )
        report.equal(analyse.status_code, 200, "/jd/analyze answers")
        analysis = analyse.json()["jd_analysis"]
        report.check(bool(analysis), "an analysis object comes back")
        report.check(
            analysis.get("keywords") or analysis.get("requirements") or analysis.get("job_title"),
            "the analysis is not empty",
            json.dumps(analysis)[:160],
        )

        # --------------------------------------------------------------- generate
        report.section("5. /generate (condition C)")
        gen = client.post(
            "/generate",
            json={
                "fields": fields,
                "authorised_modules": ["personal_info", "education", "internship", "projects"],
                "profile": PROFILE,
                "jd_text": JD_TEXT,
                "condition": "C",
                "page_title": "Graduate Programme Application",
            },
        )
        report.equal(gen.status_code, 200, "/generate answers")
        result = gen.json()
        report.equal(result["condition"], "C", "the response echoes condition C")
        report.check(result["run_id"].startswith("act-"), "the run id is an action id, not an evaluation id")
        report.check(result.get("mode") == "offline_stub", "offline mode is labelled honestly")
        report.equal(result["privacy"]["persisted"], False, "the response states nothing was persisted")
        report.equal(
            result["privacy"]["used_modules"],
            ["personal_info", "internship", "projects", "education"],
            "all four authorised modules were used",
        )
        gc = result["counts"]
        report.check(gc["total"] == len(fields), "every control appears exactly once in the response")
        report.check(gc["sensitive_skipped"] == 2, f"both document fields are skipped (got {gc['sensitive_skipped']})")
        # Reconcile the server's own summary against its own rows. `not_fillable`,
        # `sensitive_skipped`, `suggestion_offered`, `withheld_low_confidence` and
        # `missing` are a partition; `already_filled` is deliberately orthogonal,
        # so it is checked separately rather than folded into the total.
        derived = {"not_fillable": 0, "sensitive_skipped": 0, "suggestion_offered": 0,
                   "withheld_low_confidence": 0, "missing": 0}
        for row in result["fields"]:
            if not row["fillable"]:
                derived["not_fillable"] += 1
            elif row["sensitive_skipped"]:
                derived["sensitive_skipped"] += 1
            elif row["suggested_value"] is not None:
                derived["suggestion_offered"] += 1
            elif row["abstained"]:
                derived["withheld_low_confidence"] += 1
            else:
                derived["missing"] += 1
        for key, value in derived.items():
            report.equal(gc[key], value, f"counts.{key} agrees with the rows")
        report.equal(
            sum(derived.values()),
            gc["total"],
            "the five states partition every field",
        )
        report.equal(
            gc["already_filled"],
            sum(1 for row in result["fields"] if row["already_filled"]),
            "counts.already_filled agrees with the rows",
        )
        report.check(
            all(
                not row["already_filled"] or row["fillable"]
                for row in result["fields"]
            ),
            "a control we never write to is never reported as pre-filled by the user",
        )
        report.check(
            not any(row["abstained"] and row["missing"] for row in result["fields"]),
            "'withheld for weak evidence' and 'nothing to offer' are never both set",
        )
        report.check(
            not any(row["abstained"] and row["suggested_value"] is not None for row in result["fields"]),
            "a withheld field never carries a value",
        )
        report.check(
            all(row["message"] for row in result["fields"] if row["suggested_value"] is None),
            "every field without a value carries an explanation",
        )
        report.check(
            all(
                not row["sensitive_skipped"] or row["suggested_value"] is None
                for row in result["fields"]
            ),
            "no sensitive field carries a value",
        )
        report.check(
            all(
                not row["fillable"] or row["tag"] not in {"input"} or row["type"] != "hidden"
                for row in result["fields"]
            ),
            "no hidden input is fillable",
        )
        report.check(
            not any(n in gen.text for n in [PASSPORT_ON_PAGE]),
            "no document number appears anywhere in the /generate response",
        )

        rows = {row["field_id"]: row for row in result["fields"]}
        scanned_id = {row["field_id"]: row for row in scanned["fields"]}

        # ------------------------------------------------- step 6: apply + assert
        report.section("6. Controlled fill: what would be written into the page")
        touched: list[tuple[str, str, str]] = []
        refused: list[tuple[str, str]] = []
        for field_id, row in rows.items():
            source_row = scanned_id.get(field_id, {})
            label = row.get("label") or source_row.get("label") or field_id
            value = row.get("suggested_value")
            if value is None:
                refused.append((label, row.get("message") or "no value offered"))
                continue
            kind = source_row.get("type") or row.get("type")
            tag = source_row.get("tag") or row.get("tag")
            touched.append((label, kind or "text", value))
            report.check(
                kind not in {"submit", "button", "reset", "image", "file", "password", "hidden"},
                f"no value is offered for the {kind!r} control {label!r}",
            )
            report.check(
                not source_row.get("sensitive"),
                f"no value is offered for the sensitive field {label!r}",
            )

        print(f"\n  would write {len(touched)} field(s):")
        for label, kind, value in touched:
            shown = value if len(value) <= 58 else value[:55] + "..."
            print(f"    [{kind:>9}] {label:<28} = {shown}")
        print(f"\n  left for the user ({len(refused)}):")
        for label, reason in refused[:40]:
            shown = reason if len(reason) <= 62 else reason[:59] + "..."
            print(f"    {label:<34} {shown}")

        report.check(bool(touched), "at least some fields were filled in offline mode")

        sensitive_labels = {"Passport number", "NRIC / national ID number"}
        report.check(
            not any(label in sensitive_labels for label, _kind, _value in touched),
            "neither document field is in the write list",
        )
        report.check(
            not any(kind in {"submit", "button", "reset", "image", "file", "password", "hidden"}
                    for _label, kind, _value in touched),
            "nothing is written into a submit, file, password or hidden control",
        )

        # The radio group: the server must only ever offer one of the control's
        # own options, because the browser discards anything else.
        radio_rows = [
            row for row in result["fields"]
            if (scanned_id.get(row["field_id"], {}).get("type") == "radio")
        ]
        for row in radio_rows:
            options = scanned_id.get(row["field_id"], {}).get("options") or []
            if row.get("suggested_value") is not None:
                report.check(
                    row["suggested_value"] in options,
                    f"the radio answer {row['suggested_value']!r} is one of the offered options",
                )

        # Degree lands on a <select>: the answer must be one the control offers,
        # or the browser would silently drop it.
        degree_row = next(
            (row for row in result["fields"]
             if (scanned_id.get(row["field_id"], {}).get("label") == "Degree")),
            None,
        )
        if degree_row is not None:
            degree_options = scanned_id.get(degree_row["field_id"], {}).get("options") or []
            if degree_row.get("suggested_value") is not None:
                report.check(
                    degree_row["suggested_value"] in degree_options,
                    f"the degree answer {degree_row['suggested_value']!r} is one of {degree_options}",
                )
                report.check(
                    degree_row["suggested_value"] != "Please choose",
                    "the select placeholder was not offered as an answer",
                )

        report.check(
            all(
                row["confidence"] == round(row["confidence"], 4)
                for row in result["fields"]
            ),
            "no confidence value carries floating-point noise",
        )
        # The backend has no endpoint that writes to a page: filling goes
        # extension -> content script, and the content script is the only thing
        # that touches the DOM. So "the assistant cannot submit" is a property of
        # the API surface, checkable here, plus the static content-script checks
        # in section 0.
        spec = client.get("/openapi.json").json()
        paths = set(spec.get("paths", {}))
        # `/extract_resume` is in the set deliberately, and it is still not a
        # write: it takes text and returns a profile, and persists nothing. Adding
        # a route without updating this assertion is what makes a guard like this
        # worthless - it would either fail against correct code, or be loosened
        # until it passes against anything.
        report.equal(
            paths,
            {"/health", "/scan", "/generate", "/jd/fetch", "/jd/analyze", "/extract_resume"},
            "the API exposes exactly the six documented endpoints, none of them a write or submit",
        )

        # ----------------------------------------------------- condition A (no model)
        report.section("7. /generate condition A (rules only, no model)")
        gen_a = client.post(
            "/generate",
            json={
                "fields": fields,
                "authorised_modules": ["personal_info", "education", "internship", "projects"],
                "profile": PROFILE,
                "jd_text": JD_TEXT,
                "condition": "A",
            },
        )
        report.equal(gen_a.status_code, 200, "condition A answers")
        result_a = gen_a.json()
        report.check(result_a["counts"]["sensitive_skipped"] == 2, "condition A also refuses both documents")
        report.check(
            not any(n in gen_a.text for n in [PASSPORT_ON_PAGE]),
            "condition A leaks no document number either",
        )
        offered_a = [
            (row["label"], row["suggested_value"])
            for row in result_a["fields"]
            if row["suggested_value"] is not None
        ]
        print(f"\n  condition A offers {len(offered_a)} value(s), all literal profile facts:")
        for label, value in offered_a[:20]:
            shown = value if len(value) <= 52 else value[:49] + "..."
            print(f"    {label:<30} = {shown}")

        # --------------------------------------------------------- authorisation
        report.section("8. Module authorisation")
        only_personal = client.post(
            "/generate",
            json={
                "fields": fields,
                "authorised_modules": ["personal_info"],
                "profile": PROFILE,
                "jd_text": JD_TEXT,
                "condition": "A",
            },
        )
        report.equal(only_personal.status_code, 200, "an authorised-module subset is accepted")
        privacy = only_personal.json()["privacy"]
        report.equal(privacy["authorised_modules"], ["personal_info"], "only personal_info was authorised")
        report.check(
            set(privacy["dropped_modules"]) == {"education", "internship", "projects"},
            "the un-ticked modules are reported as dropped",
            str(privacy["dropped_modules"]),
        )
        # Scoped to the *offered values*, not to the whole response: "Acme Corp"
        # legitimately appears in `jd_analysis` because the user pasted a posting
        # that names it. Asserting on the raw body would fail for the right
        # behaviour, which is exactly the trap this project keeps running into.
        offered_values = [
            row["suggested_value"]
            for row in only_personal.json()["fields"]
            if row["suggested_value"] is not None
        ]
        profile_strings = [
            "Acme Corp", "Nanyang", "Data Analyst Intern", "Resume Matcher",
            "Computer Science", "Master of Science", "4.5",
        ]
        leaked = [s for s in profile_strings if any(s in v for v in offered_values)]
        report.equal(leaked, [], "no value from an un-authorised module was offered")
        report.check(
            "Acme Corp" in only_personal.text,
            "(the posting text itself may name Acme Corp - that is the user's own pasted JD, not the profile)",
        )

        # ------------------------------------------------------------------ jd/fetch
        report.section("9. /jd/fetch refusals (nothing is fetched here)")
        for url, expect_reason in [
            ("file:///etc/passwd", "unsupported_scheme"),
            ("http://127.0.0.1:9/apply", "private_host"),
            ("http://169.254.169.254/latest/meta-data/", "private_host"),
        ]:
            fetched = client.post("/jd/fetch", json={"url": url})
            body = fetched.json()
            report.equal(body.get("ok"), False, f"{url} is refused")
            report.equal(body.get("reason"), expect_reason, f"{url} reports reason {expect_reason}")
            report.check(bool(body.get("message")), f"{url} says what to do instead")

    finally:
        client.close()
        server.should_exit = True
        time.sleep(0.4)

    # ----------------------------------------------------------------- summary
    print("\n" + "=" * 72)
    total = report.passed + len(report.failures)
    print(f"RESULT: {report.passed}/{total} checks passed")
    if report.failures:
        print("\nFailures:")
        for item in report.failures:
            print(f"  - {item}")
    print("=" * 72)
    print(
        "\nScope, stated plainly: this ran against the deterministic offline stub,\n"
        "so it shows the pipeline is wired correctly and that the two hard rules\n"
        "hold on this page. It is NOT evidence about the quality of a real model's\n"
        "answers, and the checks above the network boundary (label resolution,\n"
        "React-safe writes) are approximated in Python rather than driven in a\n"
        "browser. See extension/README.md for what is still unverified."
    )
    return 0 if not report.failures else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
