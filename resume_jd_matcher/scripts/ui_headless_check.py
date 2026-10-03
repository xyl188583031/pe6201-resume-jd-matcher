"""Drive the Streamlit UI headlessly and assert the user-visible contract.

Runs `app.py` through `streamlit.testing.v1.AppTest`: no browser, no server.
The point is to catch import-time and render-time breakage after changes to the
pipeline that the UI sits on.

FORCED OFFLINE. `RJD_OFFLINE=1` routes B and C to the deterministic stub, so this
makes no API call and never reads the key. Nothing here is a model result.

    python scripts/ui_headless_check.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ["RJD_OFFLINE"] = "1"

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from streamlit.testing.v1 import AppTest  # noqa: E402

results: list[tuple[bool, str]] = []


def check(ok: bool, label: str) -> None:
    results.append((bool(ok), label))


def main() -> int:
    at = AppTest.from_file(str(REPO / "app.py"), default_timeout=240)
    at.run()
    check(not at.exception, "initial render raises no exception")
    if at.exception:
        for e in at.exception:
            print("  EXCEPTION:", e.value)
        return finish()

    warn = " ".join(w.value for w in at.warning)
    check("prototype" in warn.lower(), "prototype banner is rendered")
    check(len(at.tabs) == 3, f"three tabs present (got {len(at.tabs)})")

    # ---- drive: load a synthetic sample, then run a match (offline stub)
    box = at.selectbox(key="sample_resume")
    sample = next((o for o in box.options if o.endswith("_resume.txt")), None)
    check(sample is not None, "a synthetic sample is offered in the dropdown")
    if sample is None:
        return finish()

    box.select(sample)
    at.run()
    check(not at.exception, "re-render after sample select is clean")
    resume_val = at.text_area(key="resume_text").value or ""
    jd_val = at.text_area(key="jd_text").value or ""
    check(bool(resume_val.strip()), "resume textarea populated by the sample")
    check(bool(jd_val.strip()), "jd textarea populated by the sample")

    at.button[0].click()
    at.run()
    check(not at.exception, "run match raises no exception")
    if at.exception:
        for e in at.exception:
            print("  EXCEPTION:", e.value)

    check(any("offline" in i.value.lower() for i in at.info), "offline notice shown (stub)")

    res = at.session_state["result"] if "result" in at.session_state else None
    check(res is not None, "a result object is stored in session_state")

    check(len(at.metric) >= 4, f"four headline metrics rendered (got {len(at.metric)})")

    check(len(at.dataframe) >= 1, "prefill table rendered as a dataframe")
    if at.dataframe:
        val = at.dataframe[0].value
        rows = len(val) if hasattr(val, "__len__") else -1
        check(rows == 8, f"prefill table has 8 rows (got {rows})")
        cols = [str(c) for c in val.columns] if hasattr(val, "columns") else []
        if cols:
            check(
                "confidence" in " ".join(cols),
                "prefill table exposes per-field confidence",
            )

    if res is not None:
        check(bool(getattr(res, "prefill", None)), "result carries a prefill bundle")
        check(
            getattr(res, "condition", None) in {"A", "B", "C"},
            "result records its condition",
        )

    return finish()


def finish() -> int:
    bad = [label for ok, label in results if not ok]
    for ok, label in results:
        print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
    print(f"\n{'UI HEADLESS CHECK PASSED' if not bad else 'UI HEADLESS CHECK FAILED'}"
          f"  ({len(results) - len(bad)}/{len(results)})")
    return 0 if not bad else 1


if __name__ == "__main__":
    raise SystemExit(main())
