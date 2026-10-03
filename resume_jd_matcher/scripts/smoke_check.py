"""End-to-end smoke check, offline.

Verifies the pieces that a unit test cannot reach easily: that the Streamlit
entry point compiles, that the demo form template can be driven by a real
pipeline result, and that the report renders.

    python scripts/smoke_check.py
"""

from __future__ import annotations

import json
import py_compile
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.config import ConfidenceConfig  # noqa: E402
from src.llm.client import OpenRouterClient  # noqa: E402
from src.pipeline.prefill import load_form_schema  # noqa: E402
from src.pipeline.runner import run_case  # noqa: E402
from src.retrieval.store import build_knowledge_base  # noqa: E402

FAILURES: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    status = "PASS" if condition else "FAIL"
    print(f"  [{status}] {label}" + (f" - {detail}" if detail else ""))
    if not condition:
        FAILURES.append(label)


def main() -> int:
    print("1. Python sources compile")
    for path in sorted(REPO_ROOT.rglob("*.py")):
        if any(part in {".git", "__pycache__"} for part in path.parts):
            continue
        try:
            py_compile.compile(str(path), doraise=True)
        except py_compile.PyCompileError as exc:
            check(str(path.relative_to(REPO_ROOT)), False, str(exc).splitlines()[-1])
    check("all .py files compile", not FAILURES)

    print("\n2. Data artifacts present and consistent")
    cases_path = REPO_ROOT / "data" / "cases" / "cases.json"
    gt_path = REPO_ROOT / "data" / "cases" / "ground_truth.csv"
    check("cases.json exists", cases_path.exists())
    check("ground_truth.csv exists", gt_path.exists())
    if not cases_path.exists() or not gt_path.exists():
        return 1

    cases = json.loads(cases_path.read_text(encoding="utf-8"))["cases"]
    check("20 or 40 cases generated", len(cases) in {20, 40}, f"{len(cases)}")

    print("\n3. Knowledge base validates")
    kb = build_knowledge_base(embedding_backend="tfidf")
    check("chunk count is about 50", 45 <= kb.chunk_count <= 60, str(kb.chunk_count))
    check("store resolved", kb.backend in {"chroma", "local-numpy"}, kb.backend)

    print("\n4. Pipeline runs on a real synthetic case (offline)")
    case = cases[0]
    client = OpenRouterClient(force_offline=True)
    cfg = ConfidenceConfig.load()
    schema = load_form_schema()
    result = run_case(
        case_id=case["case_id"],
        resume_text=case["resume_text"],
        jd_text=case["jd_text"],
        condition="C",
        job_family=case["job_family"],
        variant=case["variant"],
        client=client,
        kb=kb,
        cfg=cfg,
        form_schema=schema,
    )
    check("run_case returned a result", result is not None)
    check("retrieval produced chunks", bool(result.retrieved_chunk_ids), str(result.retrieved_chunk_ids[:2]))
    check("no unhandled errors", not result.errors, "; ".join(result.errors))
    check("prefill bundle built", result.prefill is not None)
    check(
        "confidence components are condition-appropriate",
        result.assessment.components_present == ["llm_self", "retrieval"],
        str(result.assessment.components_present),
    )

    print("\n5. Demo form template can be driven by the result")
    template = (REPO_ROOT / "src" / "ui" / "demo_form.html").read_text(encoding="utf-8")
    payload = {
        "title": "Application form (simulated)",
        "subtitle": "smoke check",
        "fields": [
            {
                "name": f.name,
                "label": f.label,
                "required": False,
                "is_list": f.is_list,
                "status": f.status,
                "value": f.value,
                "confidence": f.confidence,
                "reason": f.reason,
            }
            for f in result.prefill.fields
        ],
    }
    rendered = template.replace("__PAYLOAD__", json.dumps(payload, ensure_ascii=False))
    check("placeholder substituted", "__PAYLOAD__" not in rendered)
    check("injected payload is valid JSON", _extract_payload_parses(rendered))
    check("prototype banner present in the form", "not for live sites" in rendered.lower())

    print("\n6. Streamlit entry point compiles and is importable as source")
    app_path = REPO_ROOT / "app.py"
    check("app.py exists", app_path.exists())
    source = app_path.read_text(encoding="utf-8")
    for needle in ("run_case", "demo_form.html", "abstention", "banner"):
        check(f"app.py references {needle}", needle in source)

    print("\n7. Report artefacts")
    report_path = REPO_ROOT / "artifacts" / "report.md"
    if not report_path.exists():
        # A run may write into its own out-dir (`--out-dir`), so fall back to the
        # newest per-run report before giving up. A real result is preferred over a
        # wiring check, and the path actually validated is printed, so a passing
        # check is never ambiguous about what it read.
        #
        # The fallback has to identify an EVALUATION report, not any report that
        # happens to live under `artifacts/`. It used to select on
        # `"live_api" in text`, which is a substring test over prose: the
        # browser-assistant matrix report (`artifacts/form_matrix/report.md`)
        # mentions `mode: live_api` in a limitations paragraph, so it was ranked
        # as a live evaluation run and its numbering style failed the headline
        # check below. Selection is now on the evaluation renderer's own title,
        # which only `src/evaluation/report.py` emits.
        def _is_evaluation_report(p: Path) -> bool:
            try:
                head = p.read_text(encoding="utf-8", errors="replace").lstrip()
            except OSError:
                return False
            return head.startswith("# Evaluation report")

        def _rank(p: Path) -> tuple[int, float]:
            try:
                is_live = "live_api" in p.read_text(encoding="utf-8")
            except OSError:
                is_live = False
            return (1 if is_live else 0, p.stat().st_mtime)

        per_run = sorted(
            (
                p
                for p in (REPO_ROOT / "artifacts").glob("*/report.md")
                if _is_evaluation_report(p)
            ),
            key=_rank,
            reverse=True,
        )
        if per_run:
            report_path = per_run[0]
    if report_path.exists():
        text = report_path.read_text(encoding="utf-8")
        print(f"  [INFO] validating {report_path.relative_to(REPO_ROOT).as_posix()}")
        check("report has a headline section", "## Headline (counts)" in text)
        check("report states the mode", "offline_stub" in text or "live_api" in text)
    else:
        print("  [SKIP] no evaluation report yet (run eval/run_eval.py)")

    print()
    if FAILURES:
        print(f"SMOKE CHECK FAILED: {len(FAILURES)} problem(s)")
        for item in FAILURES:
            print(f"  - {item}")
        return 1
    print("SMOKE CHECK PASSED")
    return 0


def _extract_payload_parses(rendered: str) -> bool:
    marker = "const PAYLOAD = "
    start = rendered.find(marker)
    if start == -1:
        return False
    start += len(marker)
    end = rendered.find(";\n", start)
    if end == -1:
        return False
    try:
        json.loads(rendered[start:end])
    except json.JSONDecodeError:
        return False
    return True


if __name__ == "__main__":
    raise SystemExit(main())
