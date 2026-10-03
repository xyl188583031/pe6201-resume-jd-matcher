# PE6201 — Individual Project

**Graduate Resume–JD Matcher with a RAG-Prefill Assistant**

**Author:** XIE YULONG · **Submitted:** 4 October 2026 (NTU PE6201, individual project milestone)

> Takes a synthetic resume and a pasted job description, scores the match, and offers
> *editable pre-fill suggestions* for a *simulated* application form — declining below a
> confidence threshold instead of inventing experience.

This repository **is** the submission. This file is the index to it.

---

## 0. Where each deliverable is

The brief (`final request.txt`) asks for six things. Each one, and where it lives:

| # | Deliverable | Where |
|---|---|---|
| 1 | **Report** — 1200 words ±10–15% | `report/final_report_v8.md` · also `report/final_report_v8.pdf` (6 pages, A4) and `.html` |
| 2 | **Demo video** — 5 ± 3 min, face and screen both visible | **Not in this repository** — submitted on NTULearn as `demo_video.mp4` (5 min 36 s). Narration script and shot plan: `demo_5min_script.md` |
| 3 | **Data, with an explainer** | `resume_jd_matcher/data/` — explainer at `data/README.md` |
| 4 | **Evals, with an explainer** | `resume_jd_matcher/eval/` — explainer at `eval/README.md` |
| 5 | **Code, with run instructions** | `resume_jd_matcher/` — instructions at `resume_jd_matcher/README.md` §2 |
| 6 | **Product documentation** — persona, input, output, architecture, metrics targeted and reached | `resume_jd_matcher/PRODUCT.md` |

---

## 1. The report

`report/final_report_v8.md` is the final report, and **the only version in this repository**.
It went through nine drafts; the earlier ones were the working copies that documented how
the argument changed, and they are not part of the submission.

**Word count — two readings, both given, because the two conventions in play disagree:**

| Reading | Count | In the 1020–1380 band? |
|---|---|---|
| Prose only — table contents, code, command output and appendices excluded (the convention in `PE6201_A1_FAQ.pdf` p.6) | **1,343** | yes |
| Everything, including the contents of the seven tables | **2,039** | no |

The report also exists as a rendered PDF (`final_report_v8.pdf`, 6 pages A4) and HTML. The
render chain is `report/render_report.py` + `report/report_style.css` + `report/_print_pdf.mjs`.

Its 26 course quotations are machine-checked against the slide decks for both wording and
page number by `report/_verify_v8_quotes.py`. That check reads the *extracted text* of the
decks, which is not redistributed here — it is the instructor's material. Regenerate it
with `report/extract_slides.py` if you have the course PDFs.

**Three citations point outside this repository, deliberately.** `report_en.md` is here,
but `feedback line 6` and `(feedback line 10)` refer to the instructor's interim feedback
on the problem statement — the letter that gated the time-saving metric. It is kept on
the author's machine rather than published; the report's §5, §7 and §12 carry what it
says.

## 2. The demonstration

A **5 min 36 s** 1080p screen capture with the presenter
on camera throughout. It walks the browser assistant end to end: reading a resume
PDF in the browser, pasting a job description, and accepting or declining the suggestions
the assistant offers.

> The video is **not committed**. It is submitted on NTULearn as `demo_video.mp4`,
> at the 17.6 MB re-encode of the 167 MB master. Two reasons: GitHub would have
> refused the original outright, and a public repository that carries the
> presenter's face on camera is a privacy trade the author chose not to make.

Supporting material, all in `resume_jd_matcher/demo/`:

- `demo_resume.pdf` / `demo_resume.html` — the one-page resume used on camera
- `demo_jd.txt` — the job description pasted on camera
- These are the *same* inputs as evaluation case `AIML-v01_sparse_terse-p00`, so the live
  demo and the A/B/C numbers in the report are the same instrument.

The narration script, the per-segment timing and the pre-flight checks are in
`demo_5min_script.md` at the repository root.

## 3. Data

Three kinds, all synthetic, all checked in:

| What | Where |
|---|---|
| 20 evaluation cases + ground truth | `resume_jd_matcher/data/cases/` |
| Knowledge base — 54 chunks of resume/JD guidance | `resume_jd_matcher/data/knowledge_base/` |
| Form schema and form variants used by the form matrix | `resume_jd_matcher/data/form_schema.json`, `data/test_matrix/` |

`resume_jd_matcher/data/README.md` explains the generator, the determinism guarantee
(sha256 of `cases.json` is identical across regeneration, at both n=20 and n=40), and why
every resume is synthetic. No real person's data is in this repository.

## 4. Evaluations

`resume_jd_matcher/eval/run_eval.py` runs the three conditions over the 20 cases.
`resume_jd_matcher/eval/README.md` is the explainer.

**The delivered result** — run `run-20260925-123027`, `live_api`, `openai/gpt-4o-mini`,
60 records, 0 errors:

| Condition | Passed | Fabrications | Against the 16/20 bar |
|---|---|---|---|
| A — rule-based TF-IDF, no model | **12/20** | 0 | fails |
| B — prompt-only LLM | **17/20** | 0 | passes |
| C — RAG-enhanced | **16/20** | 0 | passes, but **B beat it** |

Cost per successful task: **$0.0008 (B)** and **$0.0010 (C)**. The headline finding is that
the retrieval layer did **not** pay for itself on this corpus — see the report §10.

Two further evaluation layers are checked in, both with their own artefacts:

- **Form matrix** — 19 runs (6 forms × 5 resumes × 3 JDs), 563 controls, in
  `resume_jd_matcher/artifacts/form_matrix/` (`report.md`, `runs.jsonl`).
- **Browser check** — the unpacked extension driven in a real Edge over CDP,
  `resume_jd_matcher/extension/scripts/browser_check.mjs`.

## 5. The code

`resume_jd_matcher/` is the project. Read `resume_jd_matcher/README.md` first — it opens
with **what is verified and what is not**, before any claim, and it is the honest version
of the summary above.

Two layers:

- **Offline pipeline** (`src/`, `app.py`) — resume parsing, JD reading, retrieval, scoring,
  and the three conditions. A Streamlit UI at `app.py`.
- **Browser assistant** (`server/` + `extension/`) — a local FastAPI backend and an MV3
  browser extension that reads a PDF *in the browser* and offers per-field pre-fill
  suggestions on a simulated application form. **It has no submit route and never writes
  to a live site.**

## 6. Reproducing the results

From `resume_jd_matcher/`:

```bash
pip install -r requirements.txt

# offline — no API key, no network needed
python -m unittest discover -s tests -t .     # unit tests
python scripts/smoke_check.py                 # SMOKE CHECK PASSED
RJD_OFFLINE=1 python scripts/e2e_check.py     # 133/133 checks
python scripts/ui_headless_check.py           # 16/16 checks
python eval/run_eval.py --offline             # A/B/C, wiring check only

# the real browser layer (drives Edge over CDP, ~1 min)
bash extension/scripts/_run_browser_check.sh  # 44/44 checks

# live — needs a key
cp .env.example .env                          # put your key in OPENROUTER_API_KEY
python eval/run_eval.py --live
```

The vendored embedding model (`vendor/models/all-MiniLM-L6-v2/`) is committed so the
semantic retrieval path runs without a network. Set `HF_HUB_OFFLINE=1` to force it.

## 7. What is verified, and what is not

Stated plainly, because it matters more than the headline numbers:

**Verified** — the offline suite, the end-to-end browser-assistant path, the real-browser
extension check, and the live A/B/C run above (with a repeat run that differed in exactly
1 of 60 cells). All of it is reproduced command by command in `resume_jd_matcher/README.md` §1.1.

**Not verified, and said so in the report:**

- The **time-saved metric** (≥30%) — needs ≥3 independent timers, so it is **gated and not
  reported**; no number appears anywhere.
- The **40-case evaluation** — the generator path is deterministic and was executed, but no
  evaluation was run against the 40-case set; the delivered result is n=20.
- The **router** — the design note exists (`report/router_design_note.md`), the code does
  not; the 18/20 ceiling is arithmetic, not a measured result.
- The extension's **side-panel container** needs one human click; the panel *pages* are
  script-driven. No real PDF has reached the file input end to end.
- Nothing has been run against a **real resume, a real job ad, or a real form submission** —
  excluded by the Problem Statement by design.

## 8. Repository layout

```
.
├── README.md                  <- you are here: the submission index
├── demo_5min_script.md        <- demo narration script, timing, pre-flight checks
├── report/                    <- the report and the tools that produced it
│   ├── final_report_v8.md     <- THE REPORT (plus .pdf and .html)
│   ├── report_en.md           <- the long engineering write-up the report is cut from
│   ├── render_report.py       <- md -> html -> pdf (with report_style.css, _print_pdf.mjs)
│   ├── analyse_run.py         <- recomputes every number in the report from the run log
│   ├── extract_slides.py      <- extracts the course decks to text, for the quote check
│   └── _verify_v8_quotes.py   <- checks all 26 quotations, wording and page number
└── resume_jd_matcher/         <- the code
    ├── README.md              <- start here: verified / not verified, then how to run
    ├── PRODUCT.md             <- persona, input, output, architecture, metrics
    ├── src/  app.py           <- offline pipeline and Streamlit UI
    ├── server/                <- FastAPI backend for the browser assistant
    ├── extension/             <- MV3 browser extension
    ├── data/  eval/           <- data and evals, each with its own explainer
    ├── vendor/models/         <- vendored embedding model, so retrieval runs offline
    └── demo/                  <- the demo inputs (the video itself is on NTULearn)
```

Not committed, deliberately: the API key (`.env`), the local server token, the demo video
(privacy, and 167 MB against a 100 MB per-file limit), the instructor's own course material,
the 3.2 GB of `node_modules`, the rebuildable vector indexes
(`artifacts/chroma_db/`, `artifacts/server_index/`), and logs. `.gitignore` says which and
why.

**Also left out, and this one is a judgement call worth stating.** The repository carries
the deliverables, not the workshop. The 200-odd files that built them — the report's
atomic patch scripts, thirteen superseded report drafts, the extracted text of the
instructor's decks, the Chinese mirror of the report, the one-off probe scripts — are
untracked. They are still on the author's machine, and `.gitignore` §9 lists them. Where a
kept document cites one of them by name, the citation is to that working copy, and it says
so where it appears.
