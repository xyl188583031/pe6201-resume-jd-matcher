"""Print the actual values behind the L2 review rows.

This is a one-shot helper for the human L2 review. It is deliberately NOT
part of the normal matrix run, because the matrix is bound by H3 (no values
in any log). Here we print the values to the terminal only, and write
nothing to disk.

Run:
    RJD_OFFLINE=1 python scripts/show_l2_values.py

It prints, for the two cells selected by `render_l2()`, every field whose
field_id appears in artifacts/form_matrix/l2_review.md.
"""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# Offline, no network, no action log. Same settings the matrix uses.
os.environ["RJD_OFFLINE"] = "1"
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

# Import the matrix driver as a module.
# FIX for Python 3.12: register the module in sys.modules *before* exec_module,
# otherwise @dataclass cannot resolve `cls.__module__` during type-annotation
# processing and raises AttributeError on a NoneType.
_spec = importlib.util.spec_from_file_location(
    "rfm", REPO_ROOT / "scripts" / "run_form_matrix.py"
)
rfm = importlib.util.module_from_spec(_spec)
sys.modules["rfm"] = rfm
_spec.loader.exec_module(rfm)

import httpx  # noqa: E402

# The two cells render_l2() samples, in the order it samples them.
CELLS = [
    ("full_profile", "jd_named"),
    ("cross_domain_profile", "jd_cross_domain"),
]

# The field_ids that actually appear in l2_review.md. These are stable across
# runs because they are a fingerprint of (tag, type, name, id) of the control.
OFFERED_IDS = {
    "wf_409c03990f25",
    "wf_36bfd748fcd2",
    "wf_459eca7fb38d",
}
REFUSED_IDS = {
    "wf_4ba3bef9d2b3",
    "wf_cf2dbc97045a",
    "wf_628fecac04fd",
    "wf_f263ef9b690a",
    "wf_571f50676d64",
    "wf_f551d6320a36",
}


def main() -> int:
    resumes = {r.resume_id: r for r in rfm.load_resumes()}
    jds = {j.jd_id: j for j in rfm.load_jds()}

    form_path = rfm.FORM_DIR / "form_01_baseline.html"
    if not form_path.exists():
        print(f"FAIL: {form_path} does not exist")
        return 1
    form = rfm.Form(form_path.stem, form_path, form_path.read_text(encoding="utf-8"))
    form.fields = rfm.extract_fields(form.html)
    print(f"[info] {len(form.fields)} controls extracted from {form_path.name}")

    # Start the same backend the matrix uses.
    port = rfm.free_port()
    from server.services import KnowledgeBaseProvider

    kb = KnowledgeBaseProvider(persist_dir=rfm.OUT_DIR / "kb_index" / "chroma_db")
    if kb.get() is None:
        print(f"[warn] retrieval unavailable: {kb.error}")
    server = rfm.start_backend(port, kb)
    print(f"[info] backend on 127.0.0.1:{port}, mode=offline_stub")

    client = httpx.Client(
        base_url=f"http://127.0.0.1:{port}",
        timeout=120.0,
        headers={"X-RJD-Token": rfm.TOKEN},
    )

    try:
        for resume_id, jd_id in CELLS:
            if resume_id not in resumes:
                print(f"FAIL: resume {resume_id} not found")
                continue
            if jd_id not in jds:
                print(f"FAIL: jd {jd_id} not found")
                continue

            resume = resumes[resume_id]
            jd = jds[jd_id]

            print("\n" + "=" * 72)
            print(f"CELL: {resume_id} x {jd_id}")
            print("=" * 72)

            scan = client.post(
                "/scan",
                json={
                    "url": f"http://127.0.0.1/{form.form_id}.html",
                    "page_title": form.form_id,
                    "fields": form.fields,
                },
            )
            if scan.status_code != 200:
                print(f"FAIL: /scan HTTP {scan.status_code}: {scan.text[:200]}")
                continue

            gen = client.post(
                "/generate",
                json={
                    "fields": form.fields,
                    "authorised_modules": resume.authorised_modules,
                    "profile": resume.profile,
                    "jd_text": jd.text,
                    "condition": "C",
                    "overwrite_filled": False,
                    "scanned_field_ids": [
                        r["field_id"] for r in scan.json()["fields"]
                    ],
                },
            )
            if gen.status_code != 200:
                print(f"FAIL: /generate HTTP {gen.status_code}: {gen.text[:200]}")
                continue

            rows = {r["field_id"]: r for r in gen.json()["fields"]}

            print("\n--- offered rows (from table 1 of l2_review.md) ---")
            for fid in sorted(OFFERED_IDS):
                _print_row(fid, rows.get(fid))

            print("\n--- refused rows (from table 2 of l2_review.md) ---")
            for fid in sorted(REFUSED_IDS):
                _print_row(fid, rows.get(fid))
    finally:
        client.close()
        server.should_exit = True
        kb.close()

    print("\nDone. Values are above. Nothing was written to disk.")
    return 0


def _print_row(field_id: str, row: dict | None) -> None:
    if row is None:
        print(f"\n  field_id : {field_id}")
        print("  (NOT FOUND in this cell's response)")
        return

    value = row.get("suggested_value")
    if value is not None:
        decision = "offered"
    elif row.get("abstained"):
        decision = "abstained"
    elif row.get("missing"):
        decision = "missing"
    elif row.get("sensitive_skipped"):
        decision = "sensitive_skipped"
    else:
        decision = "other"

    print(f"\n  field_id : {field_id}")
    print(f"  label    : {row.get('label')!r}")
    print(f"  type     : {row.get('type')!r}")
    print(f"  decision : {decision}")
    print(f"  value    : {value!r}")
    print(f"  source   : {row.get('source')!r}")
    print(f"  conf     : {row.get('confidence')!r}")
    print(f"  reasons  : {row.get('reasons')}")
    if row.get("message"):
        print(f"  message  : {row['message']!r}")


if __name__ == "__main__":
    raise SystemExit(main())