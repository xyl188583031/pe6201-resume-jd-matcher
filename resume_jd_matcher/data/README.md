# `data/` — what it is, where it came from, how to rebuild it

Everything the evaluation runs on lives here. Three kinds of material: a **knowledge
base** for retrieval, a **synthetic case set** with its frozen **ground truth**, and a
small **manual test matrix** for the browser assistant. No real resume, job ad or
candidate record is anywhere in this directory.

## 1. What's in `data/`

| Path | What it is | Used by |
|---|---|---|
| `knowledge_base/kb_chunks.json` | The RAG corpus: **54 short chunks** (v2), each with a `source` | Condition C retrieval only |
| `knowledge_base/kb_chunks_v1.json` | The superseded v1 corpus (51 paraphrased chunks), kept for the change note | Nothing at run time |
| `knowledge_base/build_kb.py` | Validates and builds the corpus; **fails loudly** on a chunk over the 500-char bound | `python -m data.knowledge_base.build_kb` |
| `synthetic_generator/generate_cases.py` | Generates the cases and **writes the ground truth** | `python -m data.synthetic_generator.generate_cases` |
| `synthetic_generator/jd_bank.json` | 4 job families × titles, responsibilities, core/nice-to-have skills | The generator |
| `synthetic_generator/profiles.json` | 40 synthetic candidate profiles | The generator |
| `cases/cases.json` | **20 cases**: `resume_text`, `jd_text` and the design-level facts each was built from | `eval/run_eval.py` |
| `cases/ground_truth.csv` | Every label the scorer reads — **written before any model is called** | `src/evaluation/metrics.py` (scorer only) |
| `samples/*.txt` | A handful of resumes/JDs as plain text, for manual sanity runs | A human |
| `test_matrix/` | 6 forms' worth of inputs: 3 JDs × 5 profiles (browser-assistant checks) | `scripts/run_form_matrix.py` |
| `form_schema.json` | The simulated recruitment form's field definitions | `src/pipeline/prefill.py` |

## 2. Knowledge base — the 54 chunks

`kb_chunks.json` holds **54 chunks of 286–473 characters**, all under the 500-character
bound the Problem Statement commits to (PS §6). By source:

| Source | Chunks | Licence |
|---|---|---|
| O\*NET 31.0 occupation profiles — 4 families | 30 | CC BY 4.0 (US DOL/ETA) |
| Published CV/ATS guidance (read live, prose re-written) | 16 | Vendor pages; no third-party prose reproduced |
| ESCO v1.2.0 skill definitions | 8 | CC BY 4.0 (European Commission) |

The four O\*NET families are Data Scientists (15-2051.00), Business Intelligence Analysts
(15-2051.01), Software Developers (15-1252.00) and Project Management Specialists
(13-1082.00). The attribution obligation is discharged inside the file, in
`meta.licences`.

**Why v2 replaced v1.** v1 was 51 chunks written for this project as a *paraphrase* of
those sources; the paraphrase shared heavy boilerplate, so a lexical retriever could not
separate relevant from irrelevant chunks (calibration separation +0.0429, 15/20 queries).
v2 harvests the material from the named public platforms instead. The change note is in
`meta.change_note`.

## 3. Synthetic cases — the 20

`generate_cases.py` produces **20 cases: 5 per job family × 4 families**, drawn from **10
JD variants**, and **5 hard / 15 easy**. Each case carries its `resume_text` and `jd_text`
plus the design facts it was built from (family, variant, named/implied/required skills).

Each JD variant deliberately **implies** skills it never states literally, so that lexical
coverage and semantic coverage can be told apart instead of assumed to be the same thing.
The generator enforces three contracts **by assertion, not by hope**, and aborts the build
if any fails:

1. Every canonical skill must round-trip through its display string back to itself.
2. `match_skills(resume_text)` must equal the profile's declared skill set.
3. `match_skills(jd_text)` must equal the JD's **named** set and contain no implied skill.

A silent drift in any of the three would leave numbers that look fine and are wrong, which
is why a failed generation is preferred to a quiet one.

**Determinism.** Regeneration produces byte-identical `cases.json` and `ground_truth.csv`
(sha256-verified at both n=20 and n=40).

## 4. Ground truth, frozen before inference

`data/cases/ground_truth.csv` is written **by the generator, not by the scorer**, and is
read only by `src/evaluation/metrics.py`. The pipeline's entry point receives **only**
`resume_text` and `jd_text`; `job_family`, `variant`, `required_skills` and
`should_abstain` never cross that boundary, because feeding any of them in would be label
leakage and would inflate every metric (README §4.1). The generation order is the point:
the labels exist in a file **before** anything is run against them.

## 5. How to regenerate

```bash
python -m data.knowledge_base.build_kb          # validate + build the corpus (54 chunks)
python -m data.knowledge_base.build_kb --query "pytorch model deployment"   # ad-hoc retrieval check
python -m data.synthetic_generator.generate_cases                # 20 cases + ground truth
python -m data.synthetic_generator.generate_cases --n-cases 40   # the "or get to 40" option
```

Rebuilding the knowledge base touches only `knowledge_base/`; regenerating the cases
rewrites `cases.json`, `ground_truth.csv` and `samples/*.txt` together, because they must
stay consistent with each other.

## 6. Privacy

**All of it is synthetic.** Names, emails and phone numbers are fabricated; emails use the
reserved `example.com` / `example.edu` domains, which cannot receive mail. No real resume,
job advertisement or candidate record appears anywhere in `data/`, and the repository
records only hashes of any pasted text, never the text itself (README §9).
