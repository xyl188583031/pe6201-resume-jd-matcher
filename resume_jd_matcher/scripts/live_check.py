"""Live check of a running backend, over real HTTP.

`scripts/e2e_check.py` starts its own server in-process and runs it against the
**offline stub** - it proves the wiring and the guards, and deliberately nothing
about the model. This script is the other half: it talks to a server that is
already running with a real API key, so the live path (`live_api`,
`openai/gpt-4o-mini`) is exercised end to end, and the two hard rules are
re-checked on a response the model actually produced.

It MAKES REAL API CALLS AND COSTS MONEY - one `/jd/analyze` and one `/generate`
per run, a fraction of a cent at current gpt-4o-mini prices. It does not start a
server; start one first:

    python -m server.app --port 8765
    python scripts/live_check.py

Exit code is 0 only if every assertion holds. Output goes to stdout; this
machine's stdout capture is unreliable, so redirect to a file when running
unattended.

What it asserts, in the order it checks them:

1. `/health` reports `live_api` - an offline server would make this whole check
   meaningless, so a stub is treated as a failure rather than a pass;
2. `/scan` marks both document fields sensitive and never echoes the document
   number that is on the page;
3. `/jd/analyze` returns a structured analysis from the live model;
4. `/generate` offers only grounded values, refuses every sensitive control, and
   its own counts reconcile against its own rows.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

#: The document number deliberately typed into the demo page. It must not appear
#: anywhere in any response body.
PASSPORT_ON_PAGE = "E12345678"

PROFILE = {
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
        {"name": "Resume Matcher", "summary": "A retrieval-augmented prototype written in Python."}
    ],
}

JD_TEXT = (
    "Machine Learning Intern at Acme Corp, Singapore.\n"
    "Requirements: Python, PyTorch, SQL.\n"
    "Nice to have: Docker, Kubernetes.\n"
    "You will build training pipelines and evaluate models."
)

FIELDS = [
    {"tag": "input", "type": "text", "name": "full_name", "label": "Full name", "required": True},
    {"tag": "input", "type": "email", "name": "email", "label": "Email address", "required": True},
    {
        "tag": "select",
        "type": "select",
        "name": "degree",
        "label": "Degree",
        "options": ["BSc", "MSc", "PhD", "MBA"],
    },
    {"tag": "input", "type": "text", "name": "grad_year", "label": "Graduation year"},
    {
        "tag": "input",
        "type": "text",
        "name": "skills",
        "label": "Key skills",
        "max_length": 200,
        "help_text": "max 200 characters",
    },
    {
        "tag": "textarea",
        "type": "textarea",
        "name": "cover_letter",
        "label": "Cover letter",
        "max_length": 800,
        "required": True,
    },
    {
        "tag": "input",
        "type": "text",
        "name": "passport_no",
        "label": "Passport number",
        "current_value": PASSPORT_ON_PAGE,
    },
    {"tag": "input", "type": "text", "name": "nric", "label": "NRIC / national ID number"},
    {
        "tag": "input",
        "type": "submit",
        "name": "submit_application",
        "label": "Submit application",
        "current_value": "Submit application",
    },
    {"tag": "input", "type": "hidden", "name": "csrf", "label": "", "current_value": "tok-abc123"},
]


class Report:
    def __init__(self) -> None:
        self.passed = 0
        self.failed: list[str] = []

    def check(self, ok: bool, label: str, detail: object = "") -> bool:
        if ok:
            self.passed += 1
            print(f"  PASS  {label}")
        else:
            self.failed.append(label)
            print(f"  FAIL  {label}   [{detail}]")
        return ok

    def equal(self, actual: object, expected: object, label: str) -> bool:
        return self.check(actual == expected, label, f"got {actual!r}, want {expected!r}")

    def section(self, title: str) -> None:
        print(f"\n== {title} ==")


def post(base: str, path: str, body: dict, token: str, *, timeout: int = 900) -> tuple[int, dict, float]:
    request = urllib.request.Request(
        base + path,
        data=json.dumps(body).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/json", "X-RJD-Token": token},
    )
    started = time.time()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, json.loads(response.read()), time.time() - started
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace")
        try:
            return exc.code, json.loads(raw), time.time() - started
        except Exception:  # noqa: BLE001 - the body is not always JSON
            return exc.code, {"raw": raw[:400]}, time.time() - started


def state_of(row: dict) -> str:
    if row["sensitive_skipped"]:
        return "SENSITIVE-REFUSED"
    if not row.get("fillable", True):
        return "NOT-FILLABLE"
    if row["suggested_value"] is not None:
        return "OFFERED"
    if row["already_filled"]:
        return "USER-PREFILLED"
    if row["abstained"]:
        return "WITHHELD(weak evidence)"
    if row["missing"]:
        return "MISSING(no data)"
    return "UNACCOUNTED"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Live check of a running backend")
    parser.add_argument("--base", default="http://127.0.0.1:8765")
    parser.add_argument("--token", default=None, help="defaults to artifacts/server_token.txt")
    parser.add_argument("--condition", default="C", choices=["A", "B", "C"])
    args = parser.parse_args(argv)

    token = args.token
    if token is None:
        token = (REPO_ROOT / "artifacts" / "server_token.txt").read_text(encoding="utf-8").strip()

    report = Report()
    print(f"target: {args.base}   condition: {args.condition}")

    # ---- 1. is this actually a live server ---------------------------------
    report.section("1. The server is live, not a stub")
    try:
        with urllib.request.urlopen(args.base + "/health", timeout=10) as response:
            health = json.loads(response.read())
    except Exception as exc:  # noqa: BLE001 - a missing server is a failure, not a crash
        print(f"\nCannot reach {args.base}: {exc}")
        print("Start it first:  python -m server.app --port 8765")
        return 2
    report.equal(health.get("mode"), "live_api", "/health reports live_api")
    report.equal(health.get("bind_host"), "127.0.0.1", "the server is bound to loopback")
    report.equal(health.get("auth_required"), True, "a token is required")
    print(f"    model: {health.get('model')}")

    # ---- 2. scan -----------------------------------------------------------
    report.section("2. /scan refuses the document fields and echoes no number")
    status, scanned, seconds = post(
        args.base,
        "/scan",
        {"url": "", "page_title": "Graduate Application Form", "fields": FIELDS},
        token,
    )
    report.equal(status, 200, "/scan answered 200")
    counts = scanned.get("counts", {})
    print(f"    counts: {counts}   ({seconds:.2f}s)")
    report.equal(counts.get("total"), len(FIELDS), "every submitted control is reported back")
    report.equal(counts.get("sensitive"), 2, "both document fields are marked sensitive")
    report.check(
        PASSPORT_ON_PAGE not in json.dumps(scanned),
        "the document number on the page is not echoed by /scan",
    )

    # ---- 3. jd/analyze -----------------------------------------------------
    report.section("3. /jd/analyze returns a live analysis")
    status, analysis, seconds = post(
        args.base, "/jd/analyze", {"jd_text": JD_TEXT, "profile": PROFILE}, token
    )
    report.equal(status, 200, "/jd/analyze answered 200")
    report.equal(analysis.get("mode"), "live_api", "the analysis came from the live model")
    payload = analysis.get("jd_analysis") or {}
    report.check(bool(payload), "the analysis is not empty", sorted(payload)[:6])
    for key in ("job_title", "company"):
        print(f"    {key:12} {payload.get(key)!r}")
    print(f"    ({seconds:.2f}s)")

    # ---- 4. generate ------------------------------------------------------
    report.section("4. /generate offers only grounded values")
    status, result, seconds = post(
        args.base,
        "/generate",
        {
            "fields": FIELDS,
            "authorised_modules": ["personal_info", "education", "internship", "projects"],
            "profile": PROFILE,
            "jd_text": JD_TEXT,
            "condition": args.condition,
        },
        token,
    )
    report.equal(status, 200, "/generate answered 200")
    if status != 200:
        print(f"    {json.dumps(result)[:600]}")
        return 1
    report.equal(result.get("mode"), "live_api", "the suggestions came from the live model")
    print(f"    run_id: {result['run_id']}   ({seconds:.1f}s)")

    rows = result.get("fields", [])
    print(f"\n    {'STATE':<24} {'TYPE':<9} {'LABEL':<26} {'CONF':>7}  VALUE")
    print("    " + "-" * 96)
    for row in rows:
        value = row["suggested_value"]
        shown = "(none)" if value is None else str(value)[:36].replace("\n", " ")
        print(
            f"    {state_of(row):<24} {row['type']:<9} {(row['label'] or row['field_id'])[:25]:<26} "
            f"{row['confidence']:>7}  {shown}"
        )

    blob = json.dumps(result)
    report.check(PASSPORT_ON_PAGE not in blob, "the document number is absent from the response")
    report.check(
        not any(r["suggested_value"] is not None for r in rows if r["sensitive_skipped"]),
        "no sensitive field carries a value",
    )
    report.check(
        not any(r["current_value"] for r in rows if r["sensitive_skipped"]),
        "no sensitive field carries a value in current_value either",
    )
    report.check(
        not any(r["abstained"] and r["suggested_value"] is not None for r in rows),
        "a withheld field never carries a value",
    )
    report.check(
        not any(r["abstained"] and r["missing"] for r in rows),
        "'withheld for weak evidence' and 'nothing to offer' are never both set",
    )
    report.check(
        all(r["message"] for r in rows if r["suggested_value"] is None),
        "every field without a value carries an explanation",
    )

    counts = result.get("counts", {})
    derived = {
        "total": len(rows),
        "suggestion_offered": sum(1 for r in rows if r["suggested_value"] is not None),
        "missing": sum(1 for r in rows if r["missing"]),
        "sensitive_skipped": sum(1 for r in rows if r["sensitive_skipped"]),
        "already_filled": sum(1 for r in rows if r["already_filled"]),
        "withheld_low_confidence": sum(
            1 for r in rows if r["abstained"] and r["suggested_value"] is None
        ),
    }
    for key, value in derived.items():
        report.equal(counts.get(key), value, f"counts.{key} agrees with the rows")

    for note in result.get("notes") or []:
        print(f"    note: {note}")
    for flag in result.get("risk_flags") or []:
        print(f"    risk: {flag}")

    print(f"\nRESULT: {report.passed} passed, {len(report.failed)} failed")
    for label in report.failed:
        print(f"  FAILED: {label}")
    return 1 if report.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
