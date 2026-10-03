# Graduate Resume–JD Matcher with RAG-Prefill Assistant

Implementation of the Milestone 1 Problem Statement
(`PE6201_Project_Problem_Statement_XIE YULONG.docx`), with the intermediate
instructor feedback applied. Written against the 4 October submission milestone.

**In one line:** takes a synthetic resume and a pasted job description, scores the
match, and offers *editable pre-fill suggestions* for a *simulated* application
form — declining below a confidence of 0.4 rather than inventing experience.

---

## 1. Read this first: what is verified, and what is not

The Problem Statement's central claim is about **abstention and fabrication
behaviour under three conditions**. Whether that claim is supported depends
entirely on which parts of the system have actually been executed. So the split
comes before anything else.

### 1.1 Verified — executed on this machine, output reproduced below

| What | How it was checked | Result |
|---|---|---|
| Unit tests | `python -m unittest discover -s tests` | **268 passed, 0 failed** (109 pre-existing + 159 for the browser-assistant backend) |
| Browser assistant, end to end | `python scripts/e2e_check.py` | **133/133 checks**, real server on a loopback port, driven by `demo/application_form.html` |
| **Browser assistant, in a real browser** | `node extension/scripts/browser_check.mjs` | **37/37 checks in Edge 153**: the MV3 worker starts, the content script is injected into the live page, and a confirmed value lands in the real DOM |
| Offline end-to-end smoke | `python scripts/smoke_check.py` | **SMOKE CHECK PASSED** (21 checks across 7 sections, 0 skipped) |
| **Live A/B/C evaluation (the delivered result)** | `python eval/run_eval.py --live`, run `run-20260925-123027` | 20 cases × 3 conditions = 60 records, **0 errors**. A **12/20**, B **17/20**, C **16/20** against a 16/20 bar — **B and C pass, A does not**. 0 fabrications displayed. |
| **A second live run, same pipeline** | run `run-20260925-124706` | A 12/20, B 17/20, C 16/20. **Exactly one cell of 60 differs — C's `complete_coverage` on `AIML-v01_sparse_terse-p00`.** No pass verdict and no abstention decision changed. This is the stability check in the report's §10.6. |
| Retry/reporting path under real failures | live run aborted once by a host delete-guard; the harness now refuses to start twice against one out-dir | `eval/run_eval.py` run lock, exercised by tests |
| Full offline evaluation | `python eval/run_eval.py --offline --fresh` | 20 cases × 3 conditions, `metrics.csv` / `report.md` written. **Wiring check only** — §1.3 |
| Condition A | it contains no model, so offline == live | numbers are **real** |
| Chroma vector store | store resolved in both smoke check and eval | backend = `chroma` |
| **Semantic retrieval (`all-MiniLM-L6-v2`)** | loaded from a vendored copy under `vendor/models/` with `HF_HUB_OFFLINE=1`; the delivered run's console prints `retrieval : chroma + sentence-transformers` | loads and encodes on this machine; **the delivered A/B/C run uses the semantic backend**, re-calibrated on it (floor 0.3663 / ceiling 0.5633) |
| Test-data determinism | sha256 of `cases.json` / `ground_truth.csv` across a regeneration, at **both** n=20 and n=40 | **identical** |
| The 40-case generator path | executed in a throwaway copy of the repo | 40 cases, 4 × 10, deterministic; **a harder set** (median overlap 0.50 vs 0.86) — report §10.8 |
| Streamlit UI | script executed headless via `streamlit.testing.v1.AppTest` | 0 exceptions; sample → run → 8-field prefill table, zero below-threshold suggestions marked as offered |
| PDF ingest via `pypdf` | used to extract all 29 `study slides/*.pdf` | works; the repository's bundled fallback extractor does **not** handle these files |
| Live request **shape** | one call to OpenRouter with a deliberately invalid key | HTTP **401 "User not found."** — auth rejected, request accepted |
| OpenRouter reachability | `GET /api/v1/models` | 200, 455 models, `openai/gpt-4o-mini` present |

### 1.2 NOT verified — and why

| What | Why it could not be checked here | How to check it |
|---|---|---|
| **That the vendored embedder is byte-identical to upstream** | `cdn-lfs.huggingface.co` is still unreachable from here, so the vendored `all-MiniLM-L6-v2` copy could not be re-downloaded and checked against the published revision. That it *loads and encodes* is verified (§1.1); that it is *the same weights* is taken on trust. | compare `vendor/models/all-MiniLM-L6-v2/` sha256 against the model card where the hub is reachable |
| **Retrieval quality beyond this corpus** | the semantic backend is verified, but the similarity scale (`floor`/`ceiling`) is fitted to *this* 54-chunk corpus — see §5.1. A different corpus needs a re-derivation, not a copy of these numbers. | re-run `scripts/calibrate_similarity.py` after any corpus change (`kb_chunks.json` says so itself) |
| **Time-saved metric** | disabled by design (see §7.2) — needs ≥3 independent timers | `data/timing/timers.csv` + `timing.enabled: true` |
| `match_score` calibration | never validated against expert judgement | out of scope for this milestone |
| Real resumes / real job ads / real form submission | excluded by the Problem Statement | — |
| **A 40-case evaluation run** | the 40-case *generator* path was executed and is deterministic, but no evaluation was run against the 40-case set — the delivered results are the n=20 set | `python -m data.synthetic_generator.generate_cases --n-cases 40`, then `python eval/run_eval.py --live`; note it is a **harder** instrument, not a longer one — report §10.8 |

### 1.3 The offline numbers are a wiring check; the live numbers are the results

The offline run reports A = 12/20, B = 13/20, C = 12/20 against a 16/20 bar.
**That near-flat triple is an artefact of the stub, not a finding.** The stub is a
literal extractive rule set; it ignores the retrieved notes, so it *cannot* show a
RAG benefit. The three nearly equal scores mean "the three code paths are wired
up", nothing more. The offline report prints a `PLUMBING CHECK - NOT RESULTS`
banner, and the banner is generated by the reporting code rather than added by
hand (see `artifacts/offline_check/report.md`).

**The delivered result is the live run, not the offline one.** Offline against the
real model, on the same 20 cases:

| | A | B | C |
|---|---|---|---|
| Offline stub (wiring check) | 12/20 | 13/20 | 12/20 |
| **Live, `gpt-4o-mini`** | **12/20** | **17/20** | **16/20** |

Two things follow, and both are in the report rather than only here. First, the
stub's near-flat triple (12/13/12) was indeed an artefact — the offline stub is a
literal extractive rule set that ignores the retrieved notes, so it cannot show a
retrieval benefit, and the live run separates the model conditions from A. Second,
and less comfortably, **the separation still does not make RAG the winner**: B and
C clear the 16/20 bar and **A does not**, but **B beats C (17 vs 16)** — so on this
corpus, this embedder and these prompts the retrieval layer is worth *less than
nothing*, and the cheapest configuration is also the best. C does not beat B on
fabrication or coverage, which is the kill condition committed to in the report's
§7. A second run of the identical pipeline reproduced all three counts exactly
(one coverage cell of 60 differed). The full argument is in
`report/report_en.md` §10.

What the offline run genuinely establishes, and still does:

- Condition A is real (no model in it), and A **fails the slice bar** at 12/20.
- The abstention rule fires, and its reasons are inspectable in `runs.jsonl`.
- The fabrication guard holds: 20/20 cases with zero invented skills.
- The metric/reporting machinery is correct end-to-end.

---

### 1.4 The browser assistant (Chrome extension + local backend)

The same pipeline is also packaged as a **browser assistant**: a Manifest V3
Chrome side panel plus a local FastAPI backend. `src/` is untouched - the backend
is a thin HTTP layer that calls the same functions the A/B/C evaluation calls, so
the browser path and the evaluated path cannot drift apart.

| What | Status |
|---|---|
| `server/` - five endpoints, loopback-only, token-gated, **no write endpoint** | built; every route exercised offline by `scripts/e2e_check.py` (133/133) and by 159 unit tests |
| `extension/` - MV3, React 18 + Vite 5 + TypeScript strict | built; `tsc --noEmit` and `vite build` both clean |
| The two hard rules (never collect identity documents; never fabricate) | asserted at four boundaries each - `server/README.md` section 4 |
| `demo/application_form.html` | a self-contained demo form that **never submits anywhere** |
| **The extension's content script in a real browser** | **verified** - loaded unpacked into Edge 153 and driven over CDP (§12.5). The worker starts, the content script is injected, its field ids match the server's one-for-one, and a confirmed value reaches the live DOM. |
| **The React side panel rendering** | **NOT verified.** `chrome.sidePanel.open()` refuses a synthesised gesture, so the panel cannot be opened without a real click on the toolbar icon. Its code is type-checked and bundled and its protocol is exercised against the worker; the panel itself has never rendered. This is the last unverified surface - `extension/README.md` section 7 is one click away from closing it. |
| **A live model call through the server** | **verified over HTTP, not through the panel.** `scripts/e2e_check.py` runs against the offline stub; `scripts/live_check.py` (24/24) runs against a deployed server with a real key (`live_api`, `openai/gpt-4o-mini`), so the wire format and the guards are confirmed against a real model. Answer *quality* through the browser path is still not evidence (§12.6). |

Full detail: [`server/README.md`](server/README.md),
[`extension/README.md`](extension/README.md).

## 2. Quickstart

```bash
cd resume_jd_matcher
pip install -r requirements.txt

# --- offline: no key, no network. Everything below this line works today. ---
python -m data.knowledge_base.build_kb          # build / inspect the knowledge base
python -m data.synthetic_generator.generate_cases   # 20 cases + ground truth
python eval/run_eval.py --offline               # A/B/C -> artifacts/
python scripts/smoke_check.py                   # end-to-end sanity pass
python -m unittest discover -s tests            # 267 tests
streamlit run app.py                            # the Streamlit UI
python -m server.app                            # the browser-assistant backend (127.0.0.1:8765)
python scripts/e2e_check.py                     # extension path, end to end, offline

# --- live: real model calls ---
cp .env.example .env        # put your key in OPENROUTER_API_KEY
python eval/run_eval.py --live                  # or: --api-key sk-or-v1-...
```

Optional / larger runs:

```bash
python -m data.synthetic_generator.generate_cases --n-cases 40
python eval/run_eval.py --live --n-cases 40
python eval/run_eval.py --conditions A          # baseline alone
python scripts/calibrate_similarity.py --write-note   # re-derive the similarity floor/ceiling
```

**Note on the test runner.** `requirements.txt` lists `pytest`, but the suite is
plain `unittest` (no pytest-specific features), so it runs either way:
`python -m unittest discover -s tests` is what was used here.

### 2.1 How to verify — the six commands, and what each should print

Every command below is offline (`RJD_OFFLINE=1`) unless marked. Run them from
`resume_jd_matcher/`; each prints a single pass/fail line, so a reviewer can
confirm the claims in this README without a key or a network.

| # | Command | Expected output |
|---|---|---|
| 1 | `python -m unittest discover -s tests -t .` | `Ran 268 tests ... OK` |
| 2 | `python scripts/smoke_check.py` | `SMOKE CHECK PASSED` (21 checks) |
| 3 | `python scripts/e2e_check.py` (needs `RJD_OFFLINE=1`) | `RESULT: 133/133 checks passed` |
| 4 | `python scripts/ui_headless_check.py` | `RESULT: 16/16 checks passed` |
| 5 | `python eval/run_eval.py --offline --out-dir artifacts/kbv2_final` | writes `runs.jsonl` + `report.md`; then `python report/analyse_run.py --artifacts artifacts/kbv2_final` re-prints the A/B/C counts |
| 6 | `cd extension && npm run typecheck && npm run build` | `tsc --noEmit` clean; `dist/` written |

The real-browser layer is one further command (it drives Edge over CDP, so it
takes ~1 min):

```bash
bash extension/scripts/_run_browser_check.sh    # expects: RESULT: 44/44 checks passed
```

Caveat, stated in the same voice as §12: `44/44` covers the extension **pages**
driven over CDP. The side-panel *container* still needs one human click, and no
real PDF has reached the file input end to end (§12.6).

---

## 3. Where things are

```
config.yaml                 single source of truth for every tunable (v0.2.0)
app.py                      Streamlit UI: run a match / simulated form / report

src/
  config.py                 YAML loader -> dataclasses; banner(); api_key_from_env()
  sanitize.py               OWASP LLM01: redact instruction-hijack patterns, fence untrusted text
  taxonomy.py               skill lexicon, canonicalisation, overlap (round-trip injective)
  logging_utils.py          JSONL run log; hashes and lengths, never raw user text
  baseline/tfidf.py         condition A: TF-IDF cosine + literal skill overlap, no model
  rules/fields.py           regex field extraction + per-field confidence
  retrieval/embeddings.py   sentence-transformers -> corpus-fitted TF-IDF -> hashing (recorded)
  retrieval/store.py        Chroma or local numpy store; calibrate(); build_knowledge_base()
  llm/prompts.py            all prompts in one reviewable file
  llm/client.py             OpenRouter wrapper: retries, JSON repair, cost estimate, offline routing
  llm/offline.py            deterministic stub for B/C when there is no key
  llm/jd_parser.py          JD parse + a deterministic second pass unioned into the model's list
  llm/extractor.py          prefill extraction + the fabrication guard
  pipeline/runner.py        run_case(): the A/B/C orchestration, one result per case
  pipeline/confidence.py    the abstention rule, and the asymmetric-component handling
  pipeline/prefill.py       suggestion assembly, per-field abstention
  pipeline/pdf.py           PDF text: pypdf -> PyPDF2 -> built-in, with the engine recorded
  evaluation/metrics.py     ground truth, scoring, counts-first ConditionMetrics
  evaluation/timing.py      the gated time metric (refuses to report without >=3 timers)
  evaluation/report.py      report.md: counts-first headline + honesty notes
  ui/demo_form.html         the simulated form (self-contained, human-in-the-loop Fill)

data/      knowledge_base/kb_chunks.json (54 chunks; v1 kept as kb_chunks_v1.json)
           jd_bank.json | profiles.json | cases/ | samples/ | form_schema.json
vendor/    models/all-MiniLM-L6-v2/  vendored sentence-transformer weights (semantic, loaded offline)
eval/      run_eval.py
scripts/   calibrate_similarity.py | smoke_check.py | ui_headless_check.py | rescore_run.py
           write_kb_descriptor.py | e2e_check.py  <- the browser-assistant end-to-end check
           live_check.py  <- the same path against a running server and a real model (costs money)
server/    the browser-assistant backend (FastAPI, loopback only)
           __init__.py | app.py | schemas.py | services.py | field_map.py | jd_fetch.py | security.py
extension/ the Manifest V3 Chrome extension (React + Vite + TypeScript)
           manifest.json | package.json | vite.config.ts | tsconfig.json
           src/  types.ts | storage.ts | api.ts | background.ts | content.ts
                 sidepanel/  App.tsx | labels.ts | styles.css | components/*.tsx
           dist/ the built extension (what Load unpacked points at)
           scripts/browser_check.mjs  <- drives the built extension over CDP (Node 22, no deps)
demo/      application_form.html  <- a realistic demo form; never submits anywhere
tests/     12 test modules, 268 tests (8 pre-existing + 4 for the backend)
           server_fixtures.py is shared scaffolding, deliberately not a test module
artifacts/ kbv2_final/   runs.jsonl | metrics.csv | case_scores.csv | report.md  <- the delivered live run (run-20260925-123027)
           kbv2_repeat/  the same pipeline again (run-20260925-124706)          <- the stability pair (§10.6)
           lexical_run/  the earlier TF-IDF-era pair                            <- the baseline the report compares against (§10.9)
                         (run-20260924-014232 delivered / run-20260924-013038 repeat)
           offline_check/ | report_offline_stub.md | metrics_offline_stub.csv   <- wiring checks, NOT results
```

### 3.1 What the browser assistant adds, and what it deliberately does not

| Decision | Where it lives |
|---|---|
| abstention arithmetic, per-field withholding | `src/pipeline/confidence.py` - **unchanged** |
| literal-value and skill-claim fabrication guards | `src/llm/extractor.py`, `src/taxonomy.py` - **unchanged** |
| similarity rescaling, untrusted-JD hygiene, retrieval query shape | `src/retrieval/store.py`, `src/sanitize.py`, `src/pipeline/runner.py` - **unchanged** |
| which confidence component a web-form field gets | `server/services.py::_evidence_for_field` - **new, stated in full** |
| how free prose is checked for fabrication | `server/services.py::NarrativeGuard` - **new, stated in full** |
| web-form classification, profile rendering, deterministic facts | `server/field_map.py` - **new** |

There is exactly one implementation of every decision. Nothing under `server/`
re-implements the abstention rule or the guards, which is why a browser run and an
evaluation run cannot disagree about whether a value should have been withheld.

The new decisions are documented rather than left implicit, because a reader has to
be able to disagree with them. In one line each:

- **A field whose answer must be tailored to the posting** (narrative, skills,
  experience, project) carries the posting's retrieval score; **a plain fact about
  the person** (personal, education) carries the deterministic extraction
  confidence. Without the second rule an unrelated posting would abstain on the
  candidate's own email address, which is not a confidence judgement anybody could
  defend.
- **Prose is checked for claims, not wording** - numbers, multi-word proper names
  and skill names, all word-bounded. Applying the literal guard to a paragraph
  would withhold every honest cover letter, because no honest prose is composed
  only of words that already appear in a resume.

---

## 4. The three conditions

The conditions share every step except one, so a difference between them is
attributable to that step rather than to prompt drift:

| | What it is | Model | Retrieval |
|---|---|---|---|
| **A** | rule-based TF-IDF baseline | none | none |
| **B** | prompt-only LLM | yes | none |
| **C** | RAG-enhanced LLM | yes | yes (local vector store) |

`condition B` passes `reference_notes=None` into the same prompt template that C
passes notes into, so B and C differ only by that one section. That is what makes
B-vs-C a clean comparison rather than a prompt-tuning contest.

### 4.1 No label leakage

`run_case()` receives **only** `resume_text` and `jd_text`. The job family, the
variant, the required-skill list and `should_abstain` live in `cases.json` and are
never passed in. In particular, retrieval is **not** filtered by job family — a
real system would not know which family a job ad belongs to, and filtering by it
would leak the label straight into condition C. Retrieval therefore runs over the
whole knowledge base and has to earn its ranking on similarity alone. The
similarity calibration was derived unfiltered for the same reason.

---

## 5. Confidence and abstention

Per PS sections 4, 6 and 8:

```
confidence = 0.6 × retrieval_similarity + 0.4 × llm_self_confidence
abstain if confidence < 0.4, or if EITHER component < 0.4
```

**One asymmetry is handled explicitly.** The conditions do not all have both
components: A has lexical evidence only, B has model self-report only, C has both.
Substituting `0.0` for a missing component would make B abstain on nearly
everything purely because its absent retrieval scored zero — an implementation
artefact dressed up as a result. So the combined score is the weighted mean over
the components that *exist*, and `components_present` is carried on every
assessment and reported, so a reader can always see which formula produced a
number.

### 5.1 Retrieval similarity is rescaled, and the rescaling is derived

Raw cosine similarity on short synthetic text is not on a scale you can threshold
at 0.4. It is linearly rescaled onto `[0, 1]` using a floor and a ceiling in
`config.yaml`:

```
similarity = clip((cosine - floor) / (ceiling - floor), 0, 1)
```

- `floor = 0.3663` — **p10** of "best hit from an irrelevant family"
- `ceiling = 0.5633` — **p90** of "best hit from a relevant family"
- band: **0.197** wide
- separation (relevant median − irrelevant median): **+0.0621**

Derived by `scripts/calibrate_similarity.py` from JD-shaped probe queries built out
of the job-family skill lists, fixed seed `20260824`. The anchors are **percentiles**
of a 100-probe study, not medians — the median-anchored version was a 0.043-wide
band that pinned 15 of 20 queries to 1.000 and vetoed a perfect match. It reads **no
evaluation case and no ground-truth label**, so it cannot be fitted to the test set.
Both the component and the calibration use the **top-1** score — using a top-4 mean
for one and top-1 for the other would make the threshold meaningless. As a
by-product the 0.4 abstention line lands on raw cosine 0.445, the median of the
wrong-family distribution (0.4434).

> **These numbers belong to the semantic backend.** They were re-derived after the
> `all-MiniLM-L6-v2` weights became loadable from `vendor/models/`, because the
> TF-IDF fallback and the semantic model do not share a scale. Re-run
> `scripts/calibrate_similarity.py` whenever the corpus or the embedder changes;
> `kb_chunks.json`'s `meta.maintenance` says the same.

---

## 6. Fabrication control

Three layers, in order:

1. **Prompt** — an absent field is `null`, never a plausible guess.
2. **Deterministic guard** (`FabricationGuard`) — any value not supported by the
   source text is dropped, because prompt instructions do get ignored sometimes.
3. **Cross-check in the runner** — a model-claimed *matched skill* with no lexical
   support in the resume is stripped and the confidence is capped.

The scored check is narrow and is reported as narrow: it compares claimed
**skills** against the candidate's declared skill set. It does **not** catch an
invented employer, date, or quantity. Those remain unchecked and are listed as
such in `report.md`.

**Read the zero-fabrication column carefully.** A reports 20/20 **by construction**
— a literal keyword matcher is structurally incapable of inventing a skill, so its
zero is evidence of low capability, not good behaviour. B and C report 20/20
because they were *stopped* from fabricating. Only the B/C number is earned.

---

## 7. Evaluation design decisions

### 7.1 Counts, not percentages (instructor feedback)

> "20 cases, five per job family, against a 16/20 pass bar — one miss is five
> points. Report counts rather than percentages, or get to 40."

Counts (`x/20`) are the headline unit everywhere; percentages are supplementary.
`pass_bar_fraction: 0.80` is expressed as a fraction so it survives scaling to 40.
The generator supports both `--n-cases 20` (5/family) and `--n-cases 40`
(10/family).

### 7.2 The time-saved metric is gated, not reported

> "The 30% time saving has one timer and it is you both times — you will be faster
> the second run because you know the answers. Find three people or drop it. A/B/C
> on fabrication and skill coverage carries the claim alone."

Decision: dropped from the headline claim. It survives only as an optional
secondary metric that **refuses to emit numbers** unless at least three independent
timers signed off (`src/evaluation/timing.py`, `tests/test_timing.py`). With one
timer — the exact case the instructor flagged — it reports "Not reported", and the
report says why.

### 7.3 What makes a case "hard"

PS section 7: under 50% skill overlap, labelled `should_abstain` in
`ground_truth.csv` **before** any model runs. The current set is 5 hard / 15 easy
out of 20, which is compatible with the <30% abstention ceiling.

Both abstention bounds are reported, because either alone is gameable: a system
that abstains on everything scores 100% on hard cases and is useless; one that
never abstains scores 0% and is dangerous.

### 7.4 One caveat on condition A's abstention record

Offline, A abstained on 3/5 hard cases and 0/15 easy cases, which looks like good
discrimination. It is partly **circular**: A's confidence *is* its lexical skill
overlap, and the hard-case label *is* defined by lexical skill overlap below 0.5.
The pipeline never sees the label — this is not leakage — but the two quantities
are derived from the same statistic, so A's hit rate should not be read as
independent evidence of good abstention behaviour.

### 7.5 Why JD-requirement coverage is 1/20 for all three conditions

`complete_coverage` requires the extracted requirement set to *contain* all
named **and implied** requirements, and it is all-or-nothing. In 19 of the 20
cases at least one requirement is implied-only — present in the JD's meaning but
not in its literal text. The offline stub matches literally, so those are
lexically unreachable and the bar cannot be met. The one case that passes is
`Software_Engineering-v02_sparse_formal-p01`, which is also the only case whose
implied-requirement set is empty (verified directly against `ground_truth.csv`).

So offline, `complete_coverage` is **not a discriminating metric** — it is
measuring the stub's lack of semantic reach. It becomes meaningful only with a
real model (or a semantic embedder). Mean coverage, which is graded rather than
all-or-nothing, sits at 0.79 for all three conditions for the same reason.

---

## 8. Data

- **Knowledge base (v2)** — 54 short chunks, **286–473 characters** (all under
  the 500-char bound from PS section 6): 30 O*NET occupation chunks, 16 generic
  CV/ATS-guidance chunks and 8 ESCO skill-definition chunks, across 4 job families
  plus generic guidance, each carrying a per-chunk `source`. Built, and its chunk
  bound enforced, by `data/knowledge_base/build_kb.py`. v1 (51 paraphrase chunks)
  is kept as `kb_chunks_v1.json`.
- **Corpus sources and licences** — **O*NET 31.0** occupation profiles (Data
  Scientists 15-2051.00, Business Intelligence Analysts 15-2051.01, Software
  Developers 15-1252.00, Project Management Specialists 13-1082.00; US DOL/ETA) and
  **ESCO v1.2.0** skill definitions (European Commission), both **CC BY 4.0**; plus
  published CV/ATS guidance read from live vendor pages. No third-party prose is
  reproduced — what is taken is the *names* of skills, technologies and occupation
  tasks, and the chunk prose is written for this project. The attribution obligation
  is discharged in `meta.licences` inside `kb_chunks.json`.
- **Synthetic cases** — 20 cases (5 per family × 4 families) from 10 JD variants
  and 40 candidate profiles. 5 hard / 15 easy.
- **Ground truth is written before any inference** and stored in
  `data/cases/ground_truth.csv`. The generator enforces three contracts, each of
  which caught a real bug during development: the resume must match its declared
  skill set, the JD text's literal skills must equal the declared *named* set, and
  the declaration→display round-trip must be injective.
- **Implied vs named requirements.** Each JD variant declares responsibilities
  that *imply* skills which are deliberately not stated literally. This is what
  makes lexical-versus-semantic capability measurable instead of assumed.
- **Names, emails and phone numbers are fabricated.** Emails use the reserved
  `example.com` / `example.edu` domains.
- **Determinism** — regeneration produces byte-identical `cases.json` and
  `ground_truth.csv` (sha256 verified).

---

## 9. Privacy and safety decisions

- **In memory only.** Uploaded resumes and pasted JDs are never persisted. No
  file is written containing user text.
- **The run log records hashes and lengths, never raw text** — enforced in
  `src/logging_utils.py` by scrubbing text-like keys.
- **The JD is untrusted input** (OWASP LLM01). Instruction-hijack patterns are
  redacted and the text is fenced with explicit delimiters, with the model told
  that anything inside is data. Kept as **one line**, per the instructor's
  "keep the mitigation, do not over-claim it" — nothing auto-submits and nothing
  persists, so this is a contained risk, not the headline.
- **Human in the loop.** Every pre-fill value is a *suggestion* carrying its own
  confidence. Nothing enters the form until the user clicks Fill, and the form is
  simulated and labelled `Prototype - not for live sites` on every launch.

---

## 10. How the instructor feedback was applied

| Feedback | Action | Where |
|---|---|---|
| Report **counts** rather than percentages, or get to 40 | counts-first headline everywhere; generator supports 20 **and** 40 | `config.yaml` (`report_counts_primary`, `n_cases`, `pass_bar_fraction`), `src/evaluation/report.py` |
| The 30% time metric has one timer and it is you both times — find three people or drop it | dropped from the claim; gated behind **≥3 independent timers** and it refuses to report otherwise | `config.yaml` (`timing`), `src/evaluation/timing.py`, `tests/test_timing.py` |
| **LLM01** is fair, the JD is untrusted text — but nothing auto-submits and nothing persists. **One line.** | mitigation kept, stated in one line, not over-claimed | `config.yaml` (`privacy`), `src/sanitize.py`, §9 |
| n8n build-vs-buy experiment + rejecting LLM-as-judge for exact-match checks | kept as the build-vs-rent rationale and the scoring design | PS sections 4–5; `src/evaluation/metrics.py` uses exact/structural checks, no LLM judge |

---

## 11. Bugs found and fixed during verification

Recorded because each one was found by *running* the system, not by reading it —
and one of them was found only after the tests were already green.

1. **Sample-loading silently did nothing in the UI.** Selecting a sample from the
   dropdown left the text areas empty, so Run immediately failed with "provide a
   resume". Cause: a Streamlit `text_area` that carries a `key` reads its value
   from session state on every rerun and **ignores `value=`**, so
   `value=_read_sample(chosen)` only ever worked on the first render. Fixed with an
   `on_change` callback that pushes the sample into the session keys. Found by
   driving the UI headless with `AppTest`, not by reading the code.
2. **A field could be labelled `suggested` while displaying confidence 0.00.**
   `field_level_abstentions()` only covers the fields the extractor emitted a
   confidence for, and `build_prefill()` consulted it with a permissive
   `.get(name, False)`. A field that had a value but no confidence entry therefore
   fell through to `suggested`, contradicting the 0.4 threshold printed in the
   app's own sidebar. Fixed on both sides: the status is now derived from the
   number the user is shown (and an unknown field defaults to *withheld*), and the
   rule extractor now scores every field it emits. Covered by two regression tests.
   Verified presentation-only: `metrics.csv` is **byte-identical** before and after.
3. **School regex matched across lines** (`\s+` captured
   `"EDUCATION\nNanyang Technological University"`). Fixed to `[ \t]+`. Caught by
   comparing prefill output against ground truth.
4. **Top-3 skills compared as set equality**, which fails whenever the candidate's
   skill pool exceeds 3. Changed to a subset-plus-count rule.
5. **Retrieval similarity used a top-4 mean** while the calibration used top-1.
   Unified to top-1.
6. **Non-injective skill lexicon** — "deep learning" matched both `Deep Learning`
   and `Machine Learning`, breaking the generator's contracts. Removed the implied
   hierarchy, and removed credentials (which were leaking "Master of Science" as a
   skill).
7. **PDF fallback extracted PDF syntax as text.** Added `_looks_like_pdf` and
   `_plausible_text_lines`.

Found only once the **real model path** was exercised — the test suite was green
throughout all four of these, which is the point of listing them:

8. **The fabrication guard stripped every claim on every live call.** The guard
   compared the model's claimed skills against the canonical vocabulary with a raw
   set difference, but the model answers in its own casing (`"machine learning"`)
   while `match_skills` returns canonical names (`"Machine Learning"`). Every
   lower-cased claim looked unsupported, so the guard stripped the whole
   matched-skill list and capped confidence at `fabrication_cap` (0.35) — a silent,
   systematic forced abstention that made B and C decline on 20/20 cases. The
   offline stub returns canonical names, so no test could have seen it. Fixed by
   comparing canonically on both sides through one `has_lexical_support` predicate,
   which now has its own tests.
9. **`java` matched `javascript`, and the guard's effect was invisible.** Two
   opposite defects in the same area. The guard's fallback for out-of-vocabulary
   skills was a bare substring test, so a real fabrication — the model claiming
   Java for a candidate whose skills are Python, JavaScript, Git, REST APIs, SQL
   and Excel — passed as supported. Simultaneously, `claimed_items` was collected
   from the model's *raw* payload, so a claim the guard removed was still counted
   against the system: the guard could work perfectly and the fabrication rate
   would not move. Fixed with word-boundary matching (`java` no longer matches
   `javascript`; `JavaScript` still matches), and `claimed_items` now holds the
   post-guard lists while the new `stripped_claims` field records what was removed.
   The delivered run reports **1 stripped, 0 displayed** on that case.
10. **A composite alias defeated canonicalisation.** The résumé says
    `natural language processing (NLP)`; the ground truth lists `NLP`. Exact alias
    lookup only, so the parenthesised form matched nothing and a grounded claim was
    reported as a fabrication — inflating the one metric the instructor said could
    carry the conclusion alone. `canonicalise` now also resolves the abbreviation
    form of a composite.
11. **Two evaluation processes corrupted the run log.** A live run reported
    `A 0/0, B 7/8, C 0/20` with `NotFoundError` on every C case. Cause: two runs
    against the same `artifacts/`, where each `--fresh` truncated the other's
    `runs.jsonl` and rebuilding the Chroma store made the other process's
    collection vanish mid-flight. The numbers were **discarded, not
    reinterpreted**. `acquire_run_lock()` now refuses to start a second run against
    a live out-dir. Its own first version was wrong too — `tasklist` output decoded
    as UTF-8 raises on a non-English Windows, which made every PID look dead and
    silently disabled the guard — so the liveness check decodes leniently.
12. **A log field was computed and then dropped.** `components_present` was carried
    on the `Assessment` and exported by `as_dict()`, but `RunRecord` never copied
    it, so it was absent from `runs.jsonl`. A condition-A record therefore showed
    `llm_self_confidence: 0.0`, which reads as "the model returned zero" rather than
    "there was no model". Now logged, and a test asserts the *record* carries it.

Found by *recomputing the delivered run from its own log* — no new API calls, no
new samples, just arithmetic over records that were already on disk. These are the
ones that show why a log-plus-scorer is worth more than a saved summary table:

13. **The other guard still matched on substrings.** Anchoring the *form* payload
    guard (item 9) left the *match* payload guard — `taxonomy.has_lexical_support`,
    which decides whether a claimed skill has lexical support in the resume — on a
    bare `in` test, so `R` matched `React` and `Go` matched `Django`. Both guards now
    match on word boundaries, the same way, with tests on each (report Appendix A.5).
14. **`passed` credited a case the system had declined.** `CaseScore.passed` was
    `zero_fabrication and prefill_all_match`. A declined case emits no prefill
    values, so `prefill_all_match` was *vacuously true* and the case counted as a
    pass — an abstention scored as a success. Recomputing moved A 13→12 and C 17→16.
    The rule is now `... and not abstained`, with a test whose fixture carries a
    *populated* prefill so it cannot pass for the old reason (report Appendix A.6).
15. **`metrics.csv` reported `meets_pass_bar = 1` for every condition.**
    `write_metrics_csv` called `as_row(0.0, 0.0)` — a zero-width bar instead of the
    real 0.80 — so `passed_cases >= 0` was always true. The CSV is where a reader
    goes to check the headline, and a constant 1 made it silently useless. It now
    receives the real fraction (report Appendix A.7).
16. **The delivered `report.md` described its own retrieval wrongly.** The run
    predates `kb_descriptor.json` (the file that records which embedder and corpus
    were in force), so the rescorer fell back to "unknown" and the report printed
    `embedding backend in force: None (semantic: False)` plus a **lexical** caveat —
    while the run's own console says `retrieval : chroma + sentence-transformers`.
    `scripts/write_kb_descriptor.py` now reconstructs the descriptor from the same
    functions `build_knowledge_base` calls for its metadata (`load_chunks`,
    `make_embedder`) **without constructing the store**, so the index is not touched,
    and the report reads semantic.
17. **Two runs shared one vector index, and the second one's condition C died.** The
    run lock (item 11) protects a *run log*; both processes were nonetheless pointed
    at the same `artifacts/chroma_db`, so rebuilding the collection for one run
    deleted it out from under the other — 20 `NotFoundError`s and `A 0/0, B 7/8, C
    0/20`. Discarded, not reinterpreted. The index now lives in the run's own
    out-dir (`<out-dir>/chroma_db`) behind its own lock (`acquire_index_lock`), with
    the same PID-liveness staleness rule as the run lock;
    `tests/test_index_lock.py` covers re-entrancy, a live holder, a dead holder and
    an unreadable lock.

18. **A camelCase DOM attribute defeated every sensitive-field pattern.**
   `normalise_text` lowercased and flattened separators but never split camelCase,
   so `id="passportNo"` became `passportno` and `\bpassport\b` matched nothing.
   `passportNumber`, `idNumber`, `NRICNumber` and `drivingLicenceNumber` were all
   treated as ordinary fillable fields, and an ordinary fillable field is sent to
   the model as part of the field list. Found by a test that named the spellings a
   real form uses. Fixed by splitting `lower→Upper` and acronym→word boundaries
   before matching; the same split also fixed classification, where `fullName`,
   `jobTitle` and `graduationYear` had never matched either.

19. **A section legend decided a field's meaning.** The content script fed the
   enclosing `<fieldset><legend>` to the server as the field's `help_text`, and the
   classifier uses help text as evidence. A field labelled "Why do you want this
   role?" inside a section called "Skills and motivation" therefore matched the
   skills pattern and was classified as a skills field - so the assistant proposed
   the candidate's *skill list* as the answer to a free-text motivation question.
   Fixed by not treating section-level text as field-level help text.

20. **A trailing full stop made an honest sentence look fabricated.** The
   multi-word-proper-name pattern's character class includes `.`, so a name at the
   end of a sentence was read as `Acme Corp.` and then failed to match the source's
   `Acme Corp`. Every well-grounded cover letter that ended in an employer's name
   was withheld - the guard failing in the direction that destroys the feature's
   value. Fixed by comparing the words, not the punctuation.

21. **"A shorter answer" was allowed to be half a word.** `fit_to_length` looked for
   a space inside the truncation, which is true for `"Python, PyTo"` and false for
   `"Zha"` - so `fit_to_length("Zhang Wei", 3)` returned `"Zha"`, contradicting the
   function's own docstring. Fixed by testing whether the cut lands on a word
   boundary at all; a cut inside the first word leaves nothing and the field is
   reported unanswerable.

22. **Three response-accounting defects, all found by reconciling the server's own
   totals against its own rows.** (a) `already_filled` was read from the raw
   `value` attribute, so an `<input type="submit" value="Submit application">`
   counted as a field the user had typed in - a page where nothing had been typed
   reported four already-answered fields. (b) Controls the assistant never touches
   were in **no** bucket, because `GenerateCounts` had no `not_fillable` although
   `ScanCounts` had always reported `skipped`. (c) `abstained` was seeded from the
   raw confidence assessment, so a field with nothing to offer counted as
   "withheld for weak evidence" *and* as "missing" - and a narrative field whose
   draft was withheld as fabricated counted as neither. All three are now a clean
   partition, asserted in `tests/test_server_generate.py` and in the end-to-end
   check.

23. **A document number typed on the page was echoed straight back.** `/scan`
   returned `current_value` for every control including the passport box, and
   `/generate` returned it for fields it refused. The panel persists its drafts, so
   the value landed in browser storage. Fixed at the one place both endpoints build
   a field from the page, plus a separate blanking for non-fillable controls whose
   `value` is a CSRF token or a button caption. `already_filled` is computed before
   the blanking, so the "you have already filled this" signal survives without the
   value doing so.

24. **`unsupported_scheme` was unreachable and `private_host` was overreported.**
   `/jd/fetch` mapped *every* `is_public_url` failure to `reason="private_host"`, so
   `file:///etc/passwd` told the user their host was private when the real problem
   was the scheme - one of the documented reason codes was dead, and the wrong one
   was reported. Found while writing the refusal tests.

25. **A name at the end of a sentence was welded to the next sentence's first word.**
   `_PROPER` accepts `.` inside a token, so "I built dashboards at Acme Corp. My team
   reported weekly." matched as the single phrase `Acme Corp. My` - a string that exists
   in no source text. Every honest sentence of that shape was therefore withheld as an
   invented employer called "Acme Corp My", and the reason shown to the user was wrong
   even when the outcome happened to be right. Found by running the deployed backend
   against the live model, where the risk flag read `name 'Acme Corp My'` (§12.5). The
   match is now cut at sentence boundaries, keeping abbreviations such as `Pte. Ltd.`
   in one piece.
26. **The content script read a password box's value and sent it to the server.**
   `isFillableControl` excluded only `hidden`, and `currentValueOf` returns `input.value`
   for any input, so a typed portal password travelled over loopback as `current_value`
   even though the server refuses that control, blanks the value on the way back and
   never persists it. Measured in a real browser before the fix - the scan result held
   `current_value="Sup3rSecret!"`. A never-read list (`password`, `file`) now withholds
   the value while still reporting the control, so the panel can say why it is left
   alone.
27. **A button was named after a whole form section.** `resolveLabel`'s last resort took
   the *entire text* of the previous sibling element, so the submit control's name came
   out as "Attachments Upload CV Set a password for your applicant portal" - three
   unrelated controls stitched together. Items 19 and 27 are the same mistake found
   twice, once in `help_text` and once in `label`. Only a leaf element may now supply a
   nearby-text label.

---

## 12. Verification log

Commands run, in order, on this machine (Windows, Python 3.12.3):

```
$ python scripts/smoke_check.py
  [PASS] all .py files compile
  [PASS] 20 or 40 cases generated - 20          (excerpt: 21 checks, 0 skipped —
  [PASS] chunk count is about 50 - 54            see §12.1 for the full run)
  [PASS] store resolved - chroma
  [PASS] retrieval produced chunks - ['onet_aiml_02', 'onet_aiml_07']
  [PASS] prefill bundle built
  [PASS] injected payload is valid JSON
  [PASS] app.py references demo_form.html
  [INFO] validating artifacts/kbv2_final/report.md        <- no longer a SKIP
  [PASS] report has a headline section
  [PASS] report states the mode
SMOKE CHECK PASSED

$ python -m unittest discover -s tests
Ran 109 tests in 1.267s
OK

$ RJD_OFFLINE=1 python eval/run_eval.py --offline --fresh --out-dir artifacts/offline_check
condition                         passed    coverage     clean   prefill   abstain
------------------------------------------------------------------------------
A - rule-based TF-IDF baseline   12/20        1/20      20/20     13/20      3/20
B - prompt-only LLM             13/20        1/20      20/20     13/20      0/20
C - RAG-enhanced                12/20        1/20      20/20     13/20      1/20
------------------------------------------------------------------------------
slice bar = 16/20 cases

$ python eval/run_eval.py --live            # run-20260925-123027  (the delivered run)
run id      : run-20260925-123027
mode        : live_api
model       : openai/gpt-4o-mini
retrieval   : chroma + sentence-transformers      <- semantic, not the TF-IDF fallback
condition                         passed    coverage     clean   prefill   abstain
------------------------------------------------------------------------------
A - rule-based TF-IDF baseline   12/20        1/20      20/20     13/20      3/20
B - prompt-only LLM             17/20        1/20      20/20     17/20      0/20
C - RAG-enhanced                16/20        1/20      20/20     17/20      1/20
------------------------------------------------------------------------------
slice bar = 16/20 cases
  A: abstained on hard cases 3/5, false abstentions 0/15, fabrications 0
  B: abstained on hard cases 0/5, false abstentions 0/15, fabrications 0
  C: abstained on hard cases 0/5, false abstentions 1/15, fabrications 0
errors: 0        (60 records, ≈6 minutes)
```

**Read the two blocks together.** The offline triple (12/13/12) is a stub artefact
— three hand-written rule sets, of which the extraction one ignores the retrieved
notes, so it *cannot* show a retrieval benefit. The live run separates the model
conditions from A. But the separation still does not make RAG the winner: **B and C
clear the 16/20 bar and A does not, yet B beats C (17 vs 16)** — on this corpus,
with this embedder and these prompts, the retrieval layer is worth *less than
nothing*, and the cheapest configuration is the best one. C does not beat B on
fabrication or coverage either, which is the kill condition committed to in the
report's §7. The argument is in `report/report_en.md` §10.

Streamlit UI, driven headless (`AppTest`) — now a committed script,
`scripts/ui_headless_check.py`, run with `RJD_OFFLINE=1` so it makes **no API
call**: **16/16 checks passed**. It asserts a clean initial render, the prototype
banner, 3 tabs, a sample is offered and loads into both text areas, the offline
notice is shown on Run, no exception on Run, a result object is stored, 4 headline
metrics render, and the prefill table renders 8 rows including a per-field
`confidence` column.

### 12.1 Final regression round (after the report was written)

The report edits touched only `report/`, but the live re-runs preceded several
code changes (the `components_present` log field, the run lock, the **index lock**,
and the two scoring fixes in §11 items 14–15), so the suite was re-run end to end,
together with a fresh offline wiring check written into its own out-dir:

```
$ python -m unittest discover -s tests
Ran 109 tests in 1.267s
OK

$ python scripts/smoke_check.py
SMOKE CHECK PASSED   (21 checks, 0 skipped)

$ RJD_OFFLINE=1 python scripts/ui_headless_check.py
UI HEADLESS CHECK PASSED   (16/16)

$ RJD_OFFLINE=1 python eval/run_eval.py --offline --fresh --out-dir artifacts/offline_check
wrote artifacts/offline_check/{runs.jsonl,metrics.csv,case_scores.csv,report.md}
```

The delivered artefacts were then **re-derived from the delivered log** — no API
calls — so the derived files reflect the corrected scoring rules:

```
$ python scripts/rescore_run.py --artifacts artifacts/kbv2_final
run        : run-20260925-123027  mode=live_api  model=openai/gpt-4o-mini
pass bar   : 16/20
  A: passed  12/20  meets=0  coverage  1/20  clean 20/20  prefill 13/20  abstain  3/20
  B: passed  17/20  meets=1  coverage  1/20  clean 20/20  prefill 17/20  abstain  0/20
  C: passed  16/20  meets=1  coverage  1/20  clean 20/20  prefill 17/20  abstain  1/20
```

### 12.2 The English and the Chinese version carry the same numbers

`report/report_en.md` — the long engineering write-up the report is cut from — and its
Chinese mirror were written as independent translations, which is exactly how two
versions drift apart. A four-check verifier was written to hold them together, and it
is the thing to re-run after any edit to either. The mirror and the verifier are not
part of the submitted repository; the verifier needs both files, so both stay on the
author's machine:

- **(A) figure presence** — every load-bearing figure (the A/B/C pass counts,
  per-field prefill, abstention cells, mean confidence and coverage, token and
  latency rows, cost and cost-per-success, the §10.5 anchors, the §10.8 comparison)
  is asserted to appear in **both** files. Result: **42/42 present in both**.
- **(B) semantic-pair stability** — §10.6 re-derived from the two raw logs instead of
  trusted: **exactly 1 differing cell of 60**, a `complete_coverage` flag, and **0
  pass flips, 0 abstention flips, 0 prefill flips**. As written.
- **(C) lexical-pair stability** — §10.6's comparison figure recomputed from the
  archived lexical logs: **5 differing cells, all `top_skills`, 4 of which flipped
  the pass verdict**. As written.
- **(D) cost per successful task** — the money table's last row is *derived* and was
  wrong once (C read `$0.0009`, which is spend ÷ 17, not ÷ 16). Recomputed:
  `$0.0154 / 16 = $0.0009625 -> $0.0010`. The script fails if `$0.0009` reappears.
- `report/analyse_run.py` — every headline figure recomputed from
  `artifacts/kbv2_final/runs.jsonl` (the delivered run `run-20260925-123027`): A/B/C
  **12/17/16** passed, coverage 1/20 each, clean 20/20 each, mean confidence
  0.732/0.730/0.754, mean coverage 0.792/0.810/0.810, abstentions 3/0/1, cost
  $0.0000/$0.0137/$0.0154.

Two real inconsistencies were found this way and fixed in both versions: the
cost-per-success figure above, and the corpus row, which quoted "151–490
characters" and "8 distinct sources" against a file that measures **286–473** and
**11** distinct `source` strings. Both are now read from `kb_chunks.json` by a
patch script rather than retyped.

Live-path probe with an invalid key:

```
$ OpenRouterClient(api_key='sk-or-v1-deliberately-invalid-probe', force_offline=False)
  .complete_json(task='match')
LLMError: match failed after 3 attempts:
  Error code: 401 - {'error': {'message': 'User not found.', 'code': 401}}
```

A 401 rather than a 400 means OpenRouter accepted the endpoint, headers and
payload shape (including `response_format={"type": "json_object"}`); only
authentication failed. It also confirms the retry loop runs its 3 attempts and the
failure surfaces as an `LLMError` — a failed case, not a crash.

### 12.3 Browser-assistant regression round

Everything below was run on 2026-09-25 after the backend and extension were
finished, on the same machine (Windows, Python 3.12.3, Node 22.22.2).

```
$ python -m unittest discover -s tests -t .
Ran 267 tests in 2.075s
OK
```

The pre-existing suite specifically, to show the backend work did not disturb it:

```
$ python -m unittest tests.test_confidence tests.test_index_lock tests.test_metrics \
      tests.test_pdf_and_pipeline tests.test_prefill tests.test_sanitize \
      tests.test_taxonomy tests.test_timing
Ran 109 tests in 1.256s
OK
```

The new backend modules, by name:

```
tests.test_server_scan             29 tests   OK
tests.test_server_generate         68 tests   OK
tests.test_jd_fetch                38 tests   OK
tests.test_sensitive_and_missing   23 tests   OK
```

The end-to-end check, which starts a real server on a loopback port and drives it
from the demo page:

```
$ RJD_OFFLINE=1 python scripts/e2e_check.py
RESULT: 133/133 checks passed
```

Two of the offline checks, as run:

```
$ python scripts/smoke_check.py
SMOKE CHECK PASSED

$ RJD_OFFLINE=1 python scripts/ui_headless_check.py
UI HEADLESS CHECK PASSED  (16/16)
```

The verifier of §12.2 is not in the submitted repository — it needs the Chinese mirror,
which is not either. Its last recorded run:

```
$ RJD_OFFLINE=1 python report/_verify_report.py
SUMMARY: {'presence_missing': 0, 'semantic_ok': 0, 'lexical_ok': 0, 'cost_ok': 0}
```

The extension was type-checked and built:

```
$ npm run typecheck        # tsc --noEmit
(exit 0)
$ npm run build            # tsc --noEmit && vite build
dist/panel.html                    0.70 kB
dist/background.js                 9.56 kB
dist/content.js                   12.56 kB
dist/assets/panel-B4cL26Bf.js    261.31 kB
(exit 0)
```

with three properties asserted on the built output rather than assumed: that
`dist/content.js` is still a classic script (no `import`/`export` - a content
script that becomes a module fails to load, and the only symptom is "the extension
does nothing"), that it contains no form-submission call, and that `dist/manifest.json`
is Manifest V3.

**Not run:** the extension in a browser, and a live model call through the server.
Both are listed in section 1.2 and in `extension/README.md` section 7.

### 12.4 Bugs the end-to-end check found that the unit tests did not

Worth recording separately, because it is the argument for having written the check
at all. Items 19, 22(a), 22(b) and 23 in section 11 were found only by running the
whole path against a realistic page - each one was reported as a passing unit test
beforehand:

- 19 (section legend) was invisible to `test_server_scan.py`, which hands the
  classifier a `RawField` with a hand-written `help_text` and never a legend;
- 22(a)-(b) needed a page with a submit button, a CSRF token *and* a pre-filled
  field before the totals stopped adding up;
- 23 needed a page with a document number actually typed into it.

The lesson is the same one section 11 opens with: the unit tests confirm the
decisions, and only the end-to-end run confirms that the decisions are wired to
each other.

### 12.5 Browser round (Edge 153, unpacked extension, over CDP)

Section 12.3 approximates the content script in Python. This round runs the built
artefact instead, in a real browser:

```
$ node extension/scripts/browser_check.mjs
RESULT: 37/37 checks passed
```

Four things the round established, three of them by trying and failing first:

- **`--load-extension` is ignored by branded Chrome** (153 here) - the browser
  started, opened the page, and loaded only its three built-in component
  extensions. The same flag works in Edge. Either way a throwaway
  `--user-data-dir` is required: an existing profile ignores the flag, and remote
  debugging is refused on the default profile.
- **`chrome.sidePanel.open()` refuses a synthesised gesture** ("may only be called
  in response to a user gesture"), so the side panel cannot be opened
  programmatically over CDP. Verified rather than assumed, because it is the
  difference between "not verified" and "not verifiable here".
- **`chrome.runtime.sendMessage` from the service worker does not reach its own
  `onMessage`** ("receiving end does not exist"), and `import()` is disallowed on a
  `ServiceWorkerGlobalScope`. The check therefore drives the content script with
  `chrome.tabs.sendMessage` - the mechanism `background.ts` uses itself.
- **An MV3 worker is evicted when idle.** A message sent from the content script's
  isolated world wakes it, which is also how the worker's sender guard gets
  exercised: the page-origin request must come back with no payload.

Defects 25, 26 and 27 in section 11 all came out of this round.

### 12.6 Live round (a running server, a real model)

`scripts/e2e_check.py` starts its own server in-process and runs it against the
**offline stub**. `scripts/live_check.py` is the other half: it talks to a server
that is already running with a real key, so the live path is exercised end to end.
It makes real API calls and costs money - one `/jd/analyze` and one `/generate` per
run.

```
$ python -m server.app --port 8765
$ python scripts/live_check.py
RESULT: 24 passed, 0 failed
   /health mode=live_api  model=openai/gpt-4o-mini  bind=127.0.0.1:8765
   /scan     2 sensitive refused, document number not echoed
   /jd/analyze  live, job_title="Machine Learning Intern", company="Acme Corp"
   /generate  run act-20260925-145603: 5 offered, 2 sensitive refused,
              2 not fillable, 1 missing, 0 withheld, every count reconciled
```

Four of its assertions are the same hard rules the unit tests make, re-taken on a
response the model actually produced rather than on a stub. Two are specific to
this mode: `/health` must report `live_api` (a stub server is a *failure* here, not
a pass), and no sensitive field may carry a value in `current_value` either.

### 12.7 No-Chinese check

The repository is English outside its test data. That is a command, not an
intention, since round 3:

```
$ python scripts/check_no_chinese.py
  -> 184 file(s) scanned
...
OK - everything inside the scanned scope is English, except 13 declared exception(s) carrying 865 CJK line(s) in total.
$ echo $?
0
```

`scripts/check_no_chinese.py` scans the seven roots the round named - `README.md`,
`report/`, `server/`, `extension/`, `scripts/`, `artifacts/` and `tests/` - and
prints `file:line:col: <matched text>` for every CJK character it finds. Exit 0
means nothing was found outside the declared exceptions; exit 1 means a line
should be English and is not. It uses the standard library only, so it runs
anywhere the repository does.

The exceptions are reasons, not a suppression list, and the script prints the
reason beside the count. Four kinds are legitimate:

| Kind | Where | Why it stays |
|---|---|---|
| The detector's own subject matter | `server/field_map.py` (`SENSITIVE_PATTERNS`) | A pattern that recognises a Chinese identity-document label cannot itself be English - translating it deletes the feature |
| A test fixture | `tests/`, `demo/form_matrix/form_06_bilingual.html` | The bilingual form and the Chinese-only label are the *input under test* |
| A declared product decision | `extension/src/` panel labels | The side panel renders every label as "Chinese (English)" on purpose |
| Not in the submitted repository | `report/report_zh.md` | The Chinese mirror of the report was kept on the author's machine only. The scan runs against the working copy, so it is declared here rather than left unexplained |

Roots that are deliberately **not** scanned are printed too, with the CJK they
hold and the reason, so every exclusion is visible rather than silent: `demo/`,
`vendor/`, `eval/`, `data/`, `artifacts_preflight/`, `app.py` and the course
slides. `extension/dist/` is reported as build output - it is generated from the
scanned `extension/src/`, and a bundle is not a second decision.

Run it after any edit inside the scanned roots.

---

## 13. What to do next, in priority order

Items 1 and 2 of the previous revision's list have since been done, and the
report's §10.9 scores the predictions that were staked on them. What is left, in
order:

1. **Build the router — still the strongest product argument, still unbuilt.** A and
   B fail on *disjoint* causes: A on `education_school` extraction (6 cases), B on
   `top_skills` relevance (3 cases). A is free and instant (16 ms median vs ~8.3 s),
   so routing the cases where A's regex is weakest to the model and the rest to the
   regex should beat either condition alone. The corrected numbers make the case
   sharper than the previous revision could: A wins 12, B wins 17, and their
   failure sets barely overlap. `report/router_design_note.md` works the claim
   through instead of leaving it as an assertion: the ceiling its per-field
   counts imply is 18/20, one case above B, and whether that one case is a gain
   or a tie turns on who owns the case-level decline decision - so the gain is
   stated as *at most one case* and the note was left unbuilt.
2. **Decide what to do about `top_skills`, now that the contract is written.** The
   written contract moved B **+2** and C **+3**, taking both over the bar — below the
   +5/+6 that was predicted, because the three remaining failures are *not* one
   cause (§10.1): two are cases where the candidate's pool and the posting's
   requirements genuinely differ, and the third is a coverage question rather than a
   relevance one. Writing the contract again will not move them.
3. **Only then scale to 40 cases** — noting that the 40-case set is harder, not
   just longer (median overlap 0.50 vs 0.86, hard cases 45% vs 25%), so it needs a
   re-baseline rather than a comparison.
4. **Click the side panel through once.** The extension now loads in a real browser
   and its content script is verified against the live DOM (§12.5) - the worker
   starts, the ids match the server's, a confirmed value reaches the input, and the
   submit control is never touched. What remains is the React panel itself: it has
   never rendered, because `chrome.sidePanel.open()` needs a genuine click on the
   toolbar icon. Open the panel on `demo/application_form.html`, paste the token,
   press Scan then Generate, and confirm one row's value lands in the form. That is
   the last unverified surface; `extension/README.md` section 7 has the steps.
5. **Only if a time claim is desired:** recruit ≥3 independent timers and populate
   `data/timing/timers.csv`, then flip `timing.enabled`.
