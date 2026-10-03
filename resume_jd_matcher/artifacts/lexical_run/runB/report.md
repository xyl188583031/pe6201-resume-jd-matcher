# Evaluation report - run-20260924-014232

Generated 2026-09-23 17:52 UTC by `eval/run_eval.py`. Every number below is recomputable from `artifacts/runs.jsonl` and `data/cases/ground_truth.csv`.

## Headline (counts)

The slice bar is **16/20** cases, per Problem Statement section 9. Counts are the reporting unit: with 20 cases one case is 5 points, so a percentage hides the thing you actually need to see.

| metric | A (rule-based TF-IDF baseline) | B (prompt-only LLM) | C (RAG-enhanced) |
|---|---|---|---|
| **cases passing the slice bar** (zero fabrication AND all prefill fields exact) | 13/20 | 15/20 | 14/20 |
| JD requirement coverage, complete (named + implied) | 1/20 | 1/20 | 1/20 |
| zero fabricated skills | 20/20 | 20/20 | 20/20 |
| all four prefill fields exact | 13/20 | 15/20 | 14/20 |
|   - full name | 20/20 | 20/20 | 20/20 |
|   - email | 20/20 | 20/20 | 20/20 |
|   - education institution | 14/20 | 20/20 | 20/20 |
|   - top-3 skills | 18/20 | 15/20 | 14/20 |
| abstained (all cases) | 3/20 | 0/20 | 3/20 |
| abstained on hard cases (the good kind) | 3/5 | 0/5 | 1/5 |
| abstained on easy cases (the bad kind) | 0/15 | 0/15 | 2/15 |

Pass bar: 16/20 cases (fraction 0.80). Abstention ceiling: 30% of cases (6/20).

Mean values (context only, not the headline):

| measure | A | B | C |
|---|---|---|---|
| mean requirement coverage | 0.79 | 0.79 | 0.79 |
| mean match score | 0.0 | 0.0 | 0.0 |
| mean confidence | 0.73 | 0.74 | 0.79 |

## Detail

### Fabrication evidence

**Condition A** - 0 fabricated claim(s) across 20 cases.

**Condition B** - 0 fabricated claim(s) across 20 cases.

**Condition C** - 0 fabricated claim(s) across 20 cases.


**Read the zero-fabrication column carefully.** Two different things can produce it:

- Condition A reports zero fabrications **by construction**. A literal keyword matcher can only echo skills that are already in both documents, so it is structurally incapable of inventing one. Its zero is not evidence of good behaviour, it is evidence of low capability.
- Conditions B and C report zero because the pipeline strips any claimed skill with no lexical support in the resume, and caps confidence when it has to. That is earned, and it is the number worth comparing.

Either way the check is narrow: it compares claimed **skills** against the candidate's declared skill set. It does not catch an invented employer, date, or quantity. Those would need a separate check and are listed as unchecked below.

### Abstention behaviour

A hard case is defined in the Problem Statement as under 50% skill overlap, and is labelled `should_abstain` in ground_truth.csv before any model runs.

- **Condition A**: abstained on 3/5 hard cases and 0/15 easy cases.
  - hard cases answered anyway: AIML-v05_medium_plain-p06, Data_Analytics-v05_medium_plain-p06
- **Condition B**: abstained on 0/5 hard cases and 0/15 easy cases.
  - hard cases answered anyway: AIML-v04_sparse_verbose-p03, AIML-v05_medium_plain-p06, Software_Engineering-v05_medium_plain-p06, Data_Analytics-v05_medium_plain-p06, Product_Management-v05_medium_plain-p06
- **Condition C**: abstained on 1/5 hard cases and 2/15 easy cases.
  - false abstentions: Software_Engineering-v03_sparse_plain-p02, Data_Analytics-v01_sparse_terse-p00
  - hard cases answered anyway: AIML-v04_sparse_verbose-p03, AIML-v05_medium_plain-p06, Data_Analytics-v05_medium_plain-p06, Product_Management-v05_medium_plain-p06

Both bounds matter. A system that abstains on everything scores 100% on hard cases and is useless; a system that never abstains scores 0% and is dangerous. The pair of counts above is the whole story, which is why neither is collapsed into a single 'accuracy'.

### Prefill exact match, per field

| field | A | B | C |
|---|---|---|---|
| full name | 20/20 | 20/20 | 20/20 |
| email | 20/20 | 20/20 | 20/20 |
| education institution | 14/20 | 20/20 | 20/20 |
| top-3 skills | 18/20 | 15/20 | 14/20 |

Matching rule: name and email are compared after case- and punctuation-folding; institution likewise; **top-3 skills is compared as a SET**, so any three skills that are both (a) in the candidate's ground-truth profile and (b) required by the job description count as correct. The rule is fixed in `expected_top_skills` (the full pool) plus `expected_top_skills_n` in ground_truth.csv.

A case where the system abstained has no prefill values, so it cannot pass the slice bar. That is the literal reading of the bar in the Problem Statement, and the cost of abstention is therefore visible in the pass count rather than hidden.

### Run context

- run id: `run-20260924-014232`
- started: 2026-09-24 01:42:32
- conditions run: A, B, C
- mode: `live_api`
- model: `openai/gpt-4o-mini`
- abstention threshold: 0.4
- cases: 20

**Retrieval configuration** (determines what condition C actually was):

```json
{
  "chunks": 51,
  "store": {
    "backend": "chroma",
    "persist_dir": "D:\\NTU\\pe6201\\individual project\\resume_jd_matcher\\artifacts\\chroma_db"
  },
  "embedder": {
    "backend": "tfidf-corpus-fitted",
    "corpus_docs": 51,
    "needs_download": false,
    "semantic": false,
    "note": "lexical TF-IDF, not a semantic embedder",
    "reason": "sentence-transformers unavailable (JSONDecodeError: Expecting value: line 1 column 1 (char 0)); used corpus-fitted TF-IDF instead",
    "downgraded": true
  },
  "notes": [
    "embedding downgraded: sentence-transformers unavailable (JSONDecodeError: Expecting value: line 1 column 1 (char 0)); used corpus-fitted TF-IDF instead",
    "embedding backend is lexical, not semantic: condition C's retrieval cannot bridge synonyms in this configuration, which narrows the B-vs-C gap"
  ]
}
```

**API usage** (estimate, not an invoice):

```json
{
  "mode": "live_api",
  "model": "openai/gpt-4o-mini",
  "calls": 120,
  "prompt_tokens": 94218,
  "completion_tokens": 22416,
  "est_cost_usd": 0.027582,
  "note": "cost is an ESTIMATE from the price table in config.yaml, not an invoice"
}
```

### Outcome metric: time saved (gated)

**Not reported.** Disabled in config.yaml. The Problem Statement proposed a 30% reduction measured by timing 20 cases; with a single timer running both conditions that measurement cannot separate the tool's effect from the timer's growing familiarity with the task. Enable `timing.enabled` and supply `data/timing/timers.csv` with at least `min_independent_timers` distinct timers to report it.

### What this run does and does not establish

- All three conditions ran against the live model named above.
- Cost figures are estimates from the price table in config.yaml, not reconciled against an invoice.

Retrieval caveats:

- embedding backend in force: `tfidf-corpus-fitted` (semantic: False)
  - This backend is **lexical, not semantic**. It cannot match a synonym to a skill name, which is precisely the capability condition C is meant to add. In this configuration the B-versus-C gap is therefore narrower than the Problem Statement assumes, and any conclusion about RAG's value from this run is under-powered.
  - Install `sentence-transformers` with access to the model hub and set `retrieval.embedding_backend: sentence_transformers` to get the semantic condition.
- store notes:
  - embedding downgraded: sentence-transformers unavailable (JSONDecodeError: Expecting value: line 1 column 1 (char 0)); used corpus-fitted TF-IDF instead
  - embedding backend is lexical, not semantic: condition C's retrieval cannot bridge synonyms in this configuration, which narrows the B-vs-C gap

What is NOT checked by this evaluation:

- invented employers, dates, or quantities (only invented *skills* are checked)
- match_score calibration (reported as a mean, never validated against expert judgement)
- behaviour on real job descriptions or real resumes - the Problem Statement scopes the prototype to synthetic data and a simulated form

## Files

- `artifacts/runs.jsonl` - one JSON record per condition x case, including the retrieved chunk ids, both confidence components, and the abstention reason
- `artifacts/case_scores.csv` - the per-case audit trail behind every count above
- `artifacts/metrics.csv` - the headline table, machine-readable
