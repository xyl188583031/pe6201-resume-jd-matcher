# PRODUCT — the Resume–JD Matcher as a product

This is the product view: who it is for, what goes in and out, how it is built, and what it
set out to hit versus what it hit. The engineering view (how to run it, what is verified)
is in `README.md`; the data is in `data/README.md`; the evaluation is in `eval/README.md`.

## Persona

*Wei Ling, an MSc student finishing a lab session at 9pm, tailoring her resume to the fourth
posting of the week — she knows her own experience cold, has never seen a confidence score,
and will paste into whatever box the portal gives her.*

She is time-poor and spends 10–15 hours a week re-typing applications (PS §3). Her
constraints set the interface: a short actionable list, and an abstention that explains
itself instead of printing a bare number.

## Input

Two ways in, both implemented:

- **A resume** — a PDF, parsed **in the browser** (PDF.js) so only the extracted text
  crosses loopback and the backend has no file-handling surface; *or* a structured profile
  filled in directly.
- **A job posting** — pasted as text, or fetched from a URL by the backend.

The pasted JD is treated as **untrusted text**: hijack patterns are redacted and every
untrusted block is fenced as data rather than instructions (OWASP LLM01).

## Output

Per field, never a completed form:

- an editable **suggestion**, with a **confidence** score and the **reason** it was offered;
- or an explicit **abstention** that names why (below threshold / no supporting fact);
- a **Fill** action the user clicks — nothing is written automatically.

The system is a *reference and practice* tool. It has **no submit route** and never writes
to a live site.

## High-level architecture

```
        ┌──────────────┐   ┌────────────────┐   ┌──────────────────┐
INPUT   │  PDF resume  │   │ profile form   │   │  job posting     │
        │  (PDF.js in  │   │ (structured    │   │  (text or URL)   │
        │   browser)   │   │  fields)       │   │                  │
        └──────┬───────┘   └───────┬────────┘   └────────┬─────────┘
               │  text only        │                     │ untrusted
               └─────────┬─────────┴──────────┬──────────┘
                         ▼
        ┌────────────────────────────────────────────────────────┐
        │  LOCAL BACKEND  (FastAPI, 127.0.0.1 only)               │
        │                                                        │
        │   sanitise ──▶ JD parse ──▶ retrieve (C only) ──▶ LLM   │
        │      │            │              │                 │    │
        │   fence as    required      Chroma / numpy     OpenRouter
        │   data        skills        over 54 chunks     gpt-4o-mini
        │                                                        │
        │   ──▶ confidence (0.6×retrieval + 0.4×self-report) ──▶  │
        │   ──▶ abstain if score or either component < 0.4 ──▶    │
        │   ──▶ per-field prefill suggestions                     │
        └───────────────────────────┬────────────────────────────┘
                                    │  loopback only
                                    ▼
        ┌────────────────────────────────────────────────────────┐
        │  SIDE PANEL (MV3 extension)                            │
        │  suggestion + confidence + reason  ·  [ Fill ]  ·  ✗   │
        └───────────────────────────┬────────────────────────────┘
                                    │  on click only
                                    ▼
                     simulated form  ·  NO auto-submit
                     refuses `readonly`/`disabled` in code

HARD CONSTRAINTS (enforced in code, not by prompt)
  loopback only · no write/submit route · raw text never persisted (hashes only)
```

**What is rented versus owned.** The model (`openai/gpt-4o-mini` over OpenRouter) and the
vector store are rented; the interface, the orchestration, the data and the evaluation are
owned. Rules — not the model — decide PDF extraction, the abstention threshold, refusal of
locked controls, and identity-document detection. The full table is in `final_report_v8.md`
§5.

## Metrics targeted

From the Problem Statement §7:

| Target | Value |
|---|---|
| Pass bar on the 20-case set | **16/20** |
| Fabricated personal experience | **zero** |
| Abstention rate | **< 30%**, with abstention-on-hard-cases high |
| Time saved | ≥ 30% — **gated, not reported**: it "has one timer and it is you both times" (feedback line 10) |

## Metrics reached

Delivered run `run-20260925-123027`, `live_api`, `openai/gpt-4o-mini`, 60 records, 0 errors:

| Condition | Passed | Zero fabrication | Goal met? |
|---|---|---|---|
| A — rule-based TF-IDF | **12/20** | 20/20 | **No** — below the 16/20 bar |
| B — prompt-only LLM | **17/20** | 20/20 | **Yes** |
| C — RAG-enhanced | **16/20** | 20/20 | **Yes**, but B beat it |

**The headline finding:** the retrieval layer did **not** pay for itself — B beat C, 17 to
16, so retrieval was worth less than its cost on this corpus, and the cheapest configuration
was the best one (README §1.3). Cost per successful task was **$0.0008 (B)** and **$0.0010
(C)**; nothing fabricated in any condition. The pass/fail bar, the abstention split, and the
critique of both are in `final_report_v8.md` §7 and §10.
