# `eval/` — the evaluation, what it measures, and how to reproduce it

One entry point, one metric, three conditions. This file explains the design so a reader
can re-derive every number in the report from the files on disk.

## 1. What's in `eval/`

| Path | What it is |
|---|---|
| `eval/run_eval.py` | **The entry point.** Runs 3 conditions × N cases, scores them, writes the run log |
| `src/evaluation/metrics.py` | The scoring rules — every check is exact match or a binary predicate |
| `src/evaluation/report.py` | Turns the run log into `metrics.csv`, `case_scores.csv`, `report.md` |
| `src/evaluation/timing.py` | The gated time-saving metric (it refuses to emit a number; see README §7.2) |
| `artifacts/kbv2_final/` | The delivered run: `runs.jsonl`, `metrics.csv`, `case_scores.csv`, `report.md` |
| `report/analyse_run.py` | Recomputes every figure the report quotes, from the run log |

## 2. The three conditions

All three share one pipeline and differ in **exactly one** step, so a difference between
them is attributable to that step and not to prompt drift (README §4):

| | Condition | The one thing that differs |
|---|---|---|
| **A** | Rule-based TF-IDF baseline | No model at all — TF-IDF + exact keyword overlap. **Free**, and the baseline the course requires |
| **B** | Prompt-only LLM | One model call; no retrieval |
| **C** | RAG-enhanced | The same call, preceded by retrieval from the 54-chunk corpus |

A is the **free baseline**. Reporting a pass count without it would be
"accuracy without the majority-class baseline", which the course says "says nothing"
(Watchouts p.3).

## 3. The metric

**Cases passed out of 20**, bar **16/20**. A case passes only if it meets **both**:

1. **Zero fabricated skills** — no claimed skill outside the candidate's real profile.
2. **Exact match on the four scored prefill fields** — name, education, and top-three skills.

Delivered result (run `run-20260925-123027`, `live_api`, `openai/gpt-4o-mini`, 60 records,
0 errors):

| Condition | Passed | Zero fabrication | Prefill all-match | Declined |
|---|---|---|---|---|
| A | **12/20** | 20/20 | 13/20 | 3/20 |
| B | **17/20** | 20/20 | 17/20 | 0/20 |
| C | **16/20** | 20/20 | 17/20 | 1/20 |

**Abstention is reported as two numbers**, never one: how often it declined, *and* whether
those were the cases it would have got wrong. Either number alone is gameable — abstain on
everything and you are safe and useless; never abstain and you are confident and dangerous
(README §7.3). C's single decline is a **false** one, on an easy case.

## 4. The two layers — L1 and L2

- **L1** is the machine layer: exact-match assertions over the run log.
- **L2** is a hand-filled judgement sheet — "reading ten outputs yourself is a perfectly
  good L2" (A1_FAQ p.5). Delivered as `artifacts/form_matrix/l2_review.md`: **agree 7 /
  disagree 2 / unclear 3**, where both `disagree` rows found defects the machine checks had
  passed.

No LLM-as-judge is used anywhere: every check is exact match or a binary predicate, because
"an unaligned judge just launders bias" (Class2/C4 p.13).

## 5. How to run

```bash
# offline: no key, no network — a wiring check, not a result
python eval/run_eval.py

# the delivered run: real OpenRouter calls (needs OPENROUTER_API_KEY)
python eval/run_eval.py --live --out-dir artifacts/kbv2_final

# a single condition, or the harder 40-case instrument
python eval/run_eval.py --live --conditions A
python eval/run_eval.py --n-cases 40 --live
```

Use `--fresh` to start a new run log and `--out-dir` to keep runs from overwriting one
another. **The offline numbers are a wiring check; only the live numbers are results**
(README §1.3) — in an offline run, condition A's confidence is degenerate and B and C are
served by a deterministic stub that cannot fabricate, so its zero-fabrication figure is
structural rather than earned.

## 6. Where the results are, and how to reproduce a number

Everything the report quotes comes out of one command:

```bash
python report/analyse_run.py                       # reads artifacts/kbv2_final/
python report/analyse_run.py --run-id <run-id>     # a specific run in the log
```

It reads `artifacts/kbv2_final/runs.jsonl` plus `data/cases/ground_truth.csv` and prints a
single block of numbers — pass counts, abstentions, coverage, cost and latency. If a figure
in the report cannot be traced to a line this script printed, it should not be in the
report.
