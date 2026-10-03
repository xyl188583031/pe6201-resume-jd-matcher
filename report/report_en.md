# Graduate Resume–JD Matcher with RAG-Prefill Assistant

**PE6201 Emerging AI Technologies — End-of-Course Project (individual submission)**

| | |
|---|---|
| Author | XIE YULONG · Section B |
| Due | Sunday 4 October 2026, 23:59 SGT |
| Weight | 44% of the course mark |
| Deliverables | repository · recorded demo · this trade-off report |
| Repository | `resume_jd_matcher/` (sibling of this `report/` folder) |

**What it does, in one line.** It takes a synthetic resume and a pasted job
description, scores the match, and offers *editable* pre-fill suggestions for a
*simulated* application form — **declining below a confidence of 0.4 instead of
inventing experience.**

### How to read this report

- Sections **1–9** follow the nine sections of the Problem Statement template, in
  order, so they can be read against the Watch-outs mapping. That mapping is also
  the rubric mapping: criteria 1–4 (Problem Statement & Significance 15%,
  Business & Technical Trade-offs 25%, Implementation 35%, Demonstration &
  Communication 25%) land on §2–§3, §4–§5 and §8, §6–§7 and §9, and §1 plus §10
  respectively — the row-by-row version, with deck and page for every borrowed
  method, is in the author's traceability working copy `requirement_traceability.md`,
  kept beside the report rather than submitted with it.
- Section **10** reports the live A/B/C results; **11** prices the system;
  **12** states what the results do *not* show.
- Every number in this report was produced by a command in §14 and can be
  re-derived from `artifacts/kbv2_final/runs.jsonl` plus `data/cases/ground_truth.csv`
  without re-running the API. Nothing here is remembered from a previous run.

### Verification statement

Three things are true of this submission and I would rather state them than have
them found:

1. **The live evaluation was run** against `openai/gpt-4o-mini` over OpenRouter,
   all 20 cases × 3 conditions, and the numbers in §10 are that run
   (`run-20260925-123027`). The offline results in
   `artifacts/report_offline_stub.md` are a *wiring check* and are labelled as
   such by the reporting code itself.
2. **Semantic retrieval is now exercised, and the corpus was replaced.** The
   first live run used a corpus-fitted TF-IDF embedder — lexical, not semantic —
   because the `sentence-transformers` weights could not be fetched, and its
   corpus was 51 chunks of project-written paraphrase. Both are fixed: the model
   weights are vendored in `vendor/models/` so they load without a network, and
   the corpus is rebuilt from named public platforms (O*NET, ESCO, published ATS
   guidance) instead of paraphrase. §10 is the run on the new configuration.
   What is **not** verified is the reverse direction — no run exists with the new
   corpus on the *old* lexical embedder or the old corpus on the semantic one —
   so §10.9 lists the corpus's contribution as unattributed rather than
   attributing it.
3. **Seven defects were found by running the live path, and the test suite was
   green through all of them.** They are written up in Appendix A. Two are in my
   own scoring code and were found by *recomputing the run from its log*, not by
   running anything: they moved the headline from A 13 / B 17 / C 17 to
   **A 12 / B 17 / C 16**, and it is the corrected numbers that §10 reports. A
   guard that silently strips every claim is a more interesting finding than a
   green suite; so is a pass rule that credits a case the system declined.

---

## 1 · Working title

**Graduate Resume–JD Matcher with RAG-Prefill Assistant.**

Seven words, and it names the system and its two actions: it *matches* a graduate
résumé against a job description, and it *pre-fills* an application form from the
retrieved context. It is not "AI for job applications", which would name the
topic and decide nothing.

The word that carries the design is **pre-fill**. A system that writes your
application for you is a different product with a different risk profile. This
one proposes values into fields a human then confirms, one at a time.

## 2 · The problem, and why it matters

**One sentence.** Graduate job-seekers have no low-cost assistant that adapts a
résumé to a specific job description and pre-fills the resulting application
form *without inventing experience*, because the tools that exist either match
lexically, cost a monthly subscription, or generate confidently.

### The closest existing tools, and what they do not do

I searched rather than asserting novelty. The adjacent products are résumé–JD
scoring and rewriting tools:

| Tool | What it does | What it does not do | Price (vendor pages, Sep 2026) |
|---|---|---|---|
| Jobscan | Keyword-level ATS match rate against a pasted job description | Never declines; no form pre-fill; no abstention concept | $49.95/mo (≈$29.98/mo quarterly) |
| Teal | Résumé scoring inside a job-application tracker | Optimises *toward* the JD; no confidence signal; no pre-fill gate | $29/mo, free tier |
| Rezi | 23-checkpoint ATS readability analysis + AI rewrite | No abstention; no editable pre-fill with per-field provenance | $29/mo or $149 lifetime |
| Resume Worded / Enhancv | Rubric-style line-by-line feedback | Human reads the advice and edits manually | $24–49/mo |

*These figures come from vendor and review-marketing pages, not independent
audits; treat them as directional, which is how I use them. What matters for the
gap is structural and not price-sensitive: every one of these tools is built to
produce a score or a rewrite. **None is built to decline.** A tool can report
90/100 and still push keyword stuffing; it has no mechanism for "I cannot
support this from your data", because declining is not a feature it sells.*

That is the gap, and it is the whole reason this project exists. The value is not
that a model can match keywords — a keyword matcher does that (condition A in §10
does exactly that). The value is that the system **knows when it does not know**,
and says so in a way a user can act on.

### Quantified pain

The persona in §3 spends **10–15 hours per week** on manual tailoring and form
entry, and the work is bounded by a hard deadline she does not control: the
application window. The components are concrete: reading a posting to extract its
real requirements (minutes), reordering and rewording her own experience to
surface the relevant parts (10–30 minutes), then re-typing the same facts into a
portal's form fields (5–15 minutes) — repeated for every application.

I want to be careful about the numbers I do *not* have. Vendor pages cite broad
figures such as automated screening blocking a large share of applications, but
those come from parties selling the remedy and I have not verified them. **What I
can defend from my own data is the form-filling half**: on the 20 synthetic
cases, the four scored form fields (`full_name`, `email`, `education_school`,
`top_skills`) are recoverable from the résumé text at 20/20, 20/20, 20/20 and
17/20 respectively (§10). That is the mechanical part of the work.

### Out of scope — stated so the scope can be marked

| Out of scope | Why |
|---|---|
| Real recruitment portals, and any auto-submission | A wrong write to a real employer's system is irreversible; there is no send leg in this build at all (§8, lethal trifecta) |
| User accounts, sessions, persistence | Removes the entire class of data-at-rest risk; inputs are processed in memory and never written |
| Real résumés and real job ads | PDPA-shaped avoidance and a clean synthetic baseline; also removes consent handling from a four-week build |
| Fine-tuning | Retrieval supplies the facts here; there is no behaviour to learn (§4) |
| Claims about interview or hiring outcomes | The system does not observe outcomes, and I will not imply it does |
| The 30%-time-saved claim | Instructor feedback: one timer, and the same person both times. Demoted to a gated secondary metric (§7) |

**The decision this section makes:** the problem is a *trust* problem with a
matching problem inside it, not the other way round. Everything downstream
follows from that choice.

## 3 · Who it is for, and the domain

**One primary user, named by role:** the graduate job-seeker, specifically an MSc
student preparing applications without a careers-office appointment or a paid
tool subscription.

**Persona, one line.** *Wei Ling, an MSc student finishing a lab session at 9pm,
tailoring her résumé to the fourth posting of the week — she knows her own
experience cold, has never seen a confidence score, and will paste into whatever
box the portal gives her.*

Two things in that sentence decide the interface. She is **time-poor and
tired**, so a wall of prose is worse than useless — the output has to be a
short list she can act on. And she **has never seen a confidence number**, so a
bare "0.34" next to a field teaches her nothing. That is why the interface does
not show a score next to an abstention; it shows the *reason* ("model
self-confidence below threshold — the résumé does not state this").

**Domain.** Graduate recruitment, seen from the candidate's side. I chose it
because I am inside it — the course's own guidance is that domain knowledge is
scarcer than Python, and it is the reason I can say with confidence that the
field a candidate most often gets wrong on these forms is the graduation year,
because "2026" is simultaneously the year she finishes and the year she is
applying.

**What she does differently once it works.** She stops re-typing. She reads a
short list of match reasons and missing requirements, edits the suggestions she
agrees with, clicks Fill on a simulated form, and spends the recovered time on
interview preparation. **If nothing in that sentence changes, the problem was not
real** — so the demo is built to show exactly that path end to end.

## 4 · Why AI — and which kind

**The decision.** A rented foundation model with retrieval, plus deterministic
rules in the two places where being wrong is expensive. No fine-tuning. No agent.

### The non-AI baseline, named and measured

A **TF-IDF cosine-similarity matcher with exact keyword overlap for required
skills**. This is condition A in the evaluation and it is a real, running
component, not a straw man — it scores 12/20 on its own (§10). The course
guidance is explicit that the baseline sometimes wins, and that a baseline win is
a finding rather than a failure; A wins on two of the four job families.

### Climbing the ladder only as far as needed

| Rung | Adopted? | What it buys, and what it costs |
|---|---|---|
| Prompt a rented model | **Yes** — the whole of conditions B and C | Cheapest thing that often works. Cost: $0.0007 per case (§11) |
| RAG | **Yes** — condition C | Grounds the *phrasing guidance* on a corpus I hold and can cite. Cost: +$0.0001 per case, and it is the reason a knowledge base has to be maintained |
| Fine-tuning | **No** | Retrieval supplies facts; style is already adequate. Fine-tuning for behaviour would need curated pairs, a GPU budget and a re-run every time the corpus changes — for no measurable gain on this task |
| Agent + tools | **No** | The path is fixed: one input → retrieve → one model call → one output. There is no multi-step decision, no tool selection, and — decisively — **no write action**, which is where agents earn their risk |

### Where the model sits, and where it is kept out

The model does three jobs: parse the JD's hard requirements, explain the match,
and propose form values. It is **kept out of** three others:

- **Arithmetic.** The match score is computed in the pipeline from set
  intersection; the model's own `match_score` is logged but the scoring path does
  not depend on it.
- **Validation.** Schema checks, type checks, and the fabrication guard are code.
  The course's rule is that guarantees go in code and judgement goes in the
  prompt.
- **The abstention decision.** The threshold comparison is deterministic. The
  model *contributes* a number; it does not decide.

### Which archetype this is

Class 5's screen: *what existed before?* Two answers.

The **match-and-tailor step is Archetype A — replacing a computation that was
already being done**: a careers adviser, or the candidate herself, reading a
posting against a résumé and deciding what to surface. Same question, cheaper and
faster.

There is an **Archetype B component**, and it is the interesting one: the
*confidence* is a manufactured measurement. Before this system, nobody produced a
number saying "this match is supported to 0.92 and that one to 0.31 — decline
it." Archetype A's precondition is a labelled history of the old computation's
inputs and outputs, and this project **does not have one** — which is exactly why
the ground truth is synthetic and why §12 is as long as it is. Archetype B's
precondition is an observable proxy plus a calibration set where the truth is
known; the calibration set exists (20 cases, labels fixed before inference), and
the proxy is the two-component confidence in §7.

That analysis is not decoration. It predicts the two failure modes I actually
met: A fails by **degrading silently outside its training distribution** (the
literal matcher's blind spot on implied requirements — 1/20 coverage, §10), and B
fails because **an estimate gets read as a fact** (a confidence number that
saturates at 1.00 cannot discriminate, §12).

## 5 · Proposed approach — build vs buy

I worked down the Class 2 stack and marked each layer. The five factors are cost,
latency, control, data gravity and regulation.

| Layer | Own or rent | The actual thing | One reason |
|---|---|---|---|
| Compute & serving | **Rent** | Local `streamlit` process; the API call is the only remote compute | Nothing to keep warm; the workload is one user, interactively |
| Data + embeddings | **Build** | `data/knowledge_base/kb_chunks.json`, 54 chunks with provenance | It is the only asset a competitor calling the same API cannot copy |
| Vector store | **Rent** | `chromadb`, local persistent mode | Commodity. `chromadb` is open source and runs in-process, so "rent" here costs nothing and buys a real ANN store over a numpy loop |
| Model | **Rent** | `openai/gpt-4o-mini` via OpenRouter | Frontier-model training is a capital cost no project rents a GPU for |
| Orchestration | **Build** | `src/pipeline/runner.py` + the `src/llm/*` and `src/retrieval/*` modules | This *is* the product logic — the ordering, the sanitising, the confidence composition |
| Serving | **Rent** | Streamlit's own server | Prototype scope; no SLA exists |
| Evaluation & observability | **Build** | `eval/`, `src/evaluation/`, `artifacts/kbv2_final/runs.jsonl` | It is my risk and my accountability, and nobody else can write the rubric for my task |

**The moat is the data-and-governance pair**, which is the pattern the DBS case
teaches and the one the course repeats: *the model is rentable; your data and
your governance are not.* Concretely — anyone can call `gpt-4o-mini`. What they
cannot copy is the 54-chunk skill ontology with per-chunk provenance, the
fabrication guard's rule set, the calibrated similarity scale, and the ground
truth written before inference.

### The low-code attempt — reported because it is evidence

I spent two hours on an **n8n** workflow for JD parsing and the LLM call, and it
worked for a single JD. It broke in two places:

1. **Conditional branching on the confidence threshold.** The abstention rule is
   "abstain if EITHER component is below 0.4", and the two components are
   computed in different nodes. Expressing that as a workflow condition meant
   duplicating the threshold in two places — a silent drift waiting to happen.
2. **Chunking.** I needed control over how the knowledge base was split and how
   similarity was rescaled onto a thresholdable scale. The workflow builder's
   chunker was not inspectable in the way that mattered.

**So I moved to Python.** That is a build-versus-buy answer with a date and a
failure in it, which is worth more than a paragraph of reasoning about tools I
never opened. Going straight to code carries no penalty, but skipping the cheaper
route without trying it would have left me unable to say whether the threshold
logic *needed* code. It did.

## 6 · Data

### The retrieval corpus

| | |
|---|---|
| What | 54 short chunks, each 286–473 characters (PS bound: under 500) |
| Provenance | per-chunk `source` field, carried into every run log and into `kb_descriptor.json`; 11 distinct `source` strings |
| Composition | 30 O*NET occupation chunks, 16 generic CV/ATS-guidance chunks, 8 ESCO skill-definition chunks |
| Named sources | **O*NET 31.0** occupation profiles — Data Scientists (15-2051.00), Business Intelligence Analysts (15-2051.01), Software Developers (15-1252.00), Project Management Specialists (13-1082.00), US DOL/ETA; **ESCO v1.2.0** skill definitions, European Commission; published CV/ATS guidance read from live vendor pages |
| Licence | O*NET **CC BY 4.0**, ESCO **CC BY 4.0**. No third-party prose is reproduced: what is taken is the **skill and technology names** — short factual labels from a CC BY database — and the chunk prose around them is written for this project. The attribution obligation is discharged in `meta.licences` inside `kb_chunks.json` |
| Built by | `data/knowledge_base/build_kb.py` (committed, re-runnable) |

**The corpus was replaced, and the trigger was a measurement rather than a
feeling.** The previous revision's corpus was 51 chunks of prose written for this
project, and it shared enough boilerplate that a retriever had nothing to rank
on: the separation between the relevant and the irrelevant probe distributions
was **+0.0429**, and **15 of 20** evaluation queries saturated the calibrated
scale at 1.000. v2 harvests material from named public platforms instead, so the
chunks carry the vocabulary real postings actually use. Separation is now
**+0.0621** (§10.5). The corpus is the change the *user* of this system asked for
and the smallest of the three that moved the headline (§10.9).

**An honest note on provenance.** Chunk prose is mine; the O*NET and ESCO
contribution is the **names** of skills, technologies and occupation tasks plus a
description of what each occupation covers. I do not claim verbatim reproduction
of any source text, and `meta.provenance` in `kb_chunks.json` says so in the file
itself. Nothing here redistributes third-party prose, so the repository runs
without a third-party corpus and the licence obligation is attribution, which the
metadata file discharges.

**Does the dataset measure what I think it measures?** This is the check the
course asks for and it caught something: O*NET occupation lists describe *what a
job involves*, not *whom a specific posting will hire*. Using them as a
checklist tells me whether a candidate's skills overlap an occupation, which is
not the same as whether they will clear a given posting's screen. So the
knowledge base is used **only for method and wording guidance** in the match
prompt, never as the source of requirements — the requirements come from the JD
text itself, and from the duties it implies. That separation is enforced in
`prompts.py`.

### The evaluation set

| | |
|---|---|
| Size | 20 cases = 4 job families × 5 variants, from 10 JD variants and 40 candidate profiles |
| Variants | `sparse_terse`, `sparse_formal`, `sparse_plain`, `sparse_verbose`, `medium_plain` |
| Hard cases | 5/20, defined as skill overlap < 0.50; overlap range 0.20–1.00, median 0.86 |
| Generator | `data/synthetic_generator/generate_cases.py` (committed) |
| Deterministic? | **Yes — verified.** Re-running the generator reproduces `cases.json` and `ground_truth.csv` byte-identically |

**Ground truth was fixed before any inference ran.** `ground_truth.csv` is
written by the generator, and the evaluation script *reads* it — nothing in the
pipeline computes a label. This is the one instruction in the Watch-outs that
carries an explicit warning ("never after you have seen results"), and the file
carries `jd_named_skills`, `jd_implied_skills`, `jd_required_skills`,
`candidate_skills`, `skill_overlap`, `hard_case`, `should_abstain` and the four
expected prefill values, so every check downstream is a comparison against a
pre-committed file.

**Deliberate variation.** Length, formality and skill density vary across the
five variants; each profile's skills are drawn from a named set and each JD's
literal text is checked by the generator to contain exactly its declared skills.
The `display` mapping makes the "declared == rendered" contract enforceable, and
it *did* fail twice during development (`Deep Learning` implied `Machine
Learning`; "Master of Science" leaked in as a skill). Both are written up in
Appendix A because they are examples of the ground truth drifting, which is the
failure the Watch-outs warn about.

**Anti-leakage, checked rather than asserted.** Three specific leaks were hunted
and closed:

1. **Label leakage into the pipeline.** `run_case()` receives only `resume_text`
   and `jd_text`. `job_family` and `variant` are passed for *logging* but never
   reach a decision — verified by reading the function, and the code carries a
   comment at the retrieval call site explaining that filtering by family would
   leak the label and that the calibration was deliberately derived unfiltered.
2. **Leakage through the classifier's own hand.** Condition A's abstention record
   is partly circular: A's confidence *is* lexical skill overlap, and "hard case"
   *is* overlap < 0.5. The label never enters the pipeline, but the two quantities
   come from the same statistic, so A's 3/5 hard-case hits are **not** independent
   evidence. Reported here, and again in §10, rather than quietly banked.
3. **Leakage in the report.** I checked whether the exact-match prefill fields
   could be satisfied by echoing the résumé header. `email` and `full_name` can —
   which is why they are not evidence of model quality, and why the prefill
   metric is reported per field rather than as one number.

## 7 · Success metric and how I evaluate it

### The metric, with a target and a baseline

**Primary metric: cases passed out of 20, pass bar 16/20.** A case passes when
the system's output contains **zero fabricated skills** *and* the four scored
prefill fields match ground truth exactly. Baseline: **condition A**, the
rule-based matcher.

**Counts, not percentages.** Instructor feedback was explicit — at n=20 one case
is five points, so percentages imply precision that does not exist.
`metrics.csv` carries `x/n` as the primary form and every table in §10 is
count-first. The generator can also produce a 40-case set (`--n-cases 40`), which
is the alternative the feedback offered; I kept 20 and report counts.

**Is it internally consistent?** The fabrication check and the coverage check
point in opposite directions — a system that outputs nothing has zero
fabrications and zero coverage. That is why `passed` requires both, why
abstention is *reported separately* and never folded into the total, and why
coverage is reported as a mean as well as an all-or-nothing count.

**Is the set large enough that one flaky case does not move the headline?** No,
and I will not pretend otherwise: at n=20 one case is 5 points. The mitigation is
that the 40-case path exists and is committed, and that §10 names every
individual failing case rather than only the total.

### The abstention mechanism, and the two numbers the course asks for

The rule is deterministic and lives in `src/pipeline/confidence.py`:

```
confidence = w_retrieval · retrieval_similarity + w_llm · llm_self_confidence
abstain if  confidence < 0.4
        OR  either present component < 0.4
```

- `retrieval_similarity` is the **top-1** calibrated cosine score of the best
  retrieved chunk, rescaled onto [0,1] by a floor/ceiling pair that was *derived*
  (`scripts/calibrate_similarity.py`, fixed seed) rather than hand-tuned.
- `llm_self_confidence` is the model's own 0–1 estimate, asked for explicitly
  with the instruction not to default to 0.9.
- The two components are **not always both present**. Condition A has no model;
  condition B has no retrieval. Substituting 0.0 for the missing one would be an
  implementation artefact dressed up as a result — B would abstain on nearly
  everything because its absent retrieval scored zero. So the combined score is a
  renormalised weighted mean over the components that *exist*, and
  `components_present` is logged on every case so a reader can see which formula
  produced a given number.

**Why the either-component rule matters.** It is the PS section 8 Risk 2
mitigation, and it targets the silent failure specifically: good retrieved
context with a model that is confidently wrong about it. If the best passage is a
poor match for the question, the grounding is weak no matter how fluent the
answer is.

**The two numbers.** Watch-outs §7 asks for both: *how often the system abstains*,
and *whether the cases it abstained on were the ones it would have got wrong*. §10
reports both, split by hard/easy, because either alone is gameable — a system that
abstains on everything is safe and useless, one that never abstains is confident
and dangerous.

**The threshold is a design decision, so here is the paragraph.** 0.4 was chosen
in the Problem Statement before any data existed. Two live runs later the honest
answer is that **the value did not change and the meaning did**. On the lexical
run the retrieval component was 1.000 on 15 of 20 cases, so a 0.4 test on it was
arbitrary. After re-deriving the scale on the semantic backend (§10.5) the
component takes 16 distinct values and 0.4 sits at raw cosine **0.445 — the
median of the wrong-family retrieval distribution**. That is a defensible
sentence: the system declines when a retrieval is no better than a typical
wrong-subject retrieval. What has *not* changed is the asymmetry between the two
components — the model's self-confidence clusters at 0.6–0.8 in every run and
never approaches 0.4, so in practice the retrieval component decides. §12.1 keeps
that on the list.

### Why there is no LLM-as-judge here

Every check in `src/evaluation/metrics.py` is exact match or a binary,
human-verifiable predicate. Two reasons:

1. The instructor's feedback on the problem statement called this the right call.
2. The course's own material makes the case: an unaligned judge "just launders
   bias", and a judge is *a component of the system, not a source of truth* — if
   I used one I would owe a precision/recall measurement of the judge against
   hand labels, and I would rather spend that effort on the thing being judged.

**What that decision costs me, stated plainly.** Exact match is brittle. A
prefill field is scored right or wrong, so a model returning
`"Nanyang Technological University"` where ground truth holds
`"Nanyang Technological University, Singapore"` scores zero on a difference a
human would call cosmetic. §10 shows this is not hypothetical. A judge would
paper over it; instead I report per-field exact match and name the failures.

### Measuring before building

The course's measure-before-build list, answered: **baseline** — condition A on
the same 20 cases; **one primary metric** — cases passed, named in advance, and
one, not five; **horizon** — immediate for a per-case check, which is why this
metric can be read from a single run; **confound** — the embedding backend was the
big one in the first run, since a lexical embedder suppresses condition C's
advantage; it is now resolved and replaced by a smaller one, that the corpus and
the embedder changed in the same step, which §10.9 reports rather than
disentangles; **counterfactual** — none exists, this is a fixed test
set and not an online experiment, and §12 says so; **kill condition** — if C does
not beat A on fabrication *and* coverage, the retrieval layer is not earning its
keep. It is reported either way in §10.

## 8 · Risks, limitations and responsible use

### Every risk with its mitigation on the same line

| # | Risk | Mitigation, as built |
|---|---|---|
| 1 | **Hallucinated experience** — the model invents a job, a skill or a metric | Three layers, in code: (a) `NO_FABRICATION` instruction in every system prompt; (b) a **fabrication guard** that strips any claimed skill with no lexical support in the candidate's own text and caps confidence at `fabrication_cap` (0.35, below threshold, so a caught fabrication forces a decline); (c) `FabricationGuard` in the prefill extractor drops ungrounded values. All prefill appears as *editable suggestions*, inserted only on the user's click |
| 2 | **Silent failure** — retrieval is irrelevant but the output is confident (PS §8 Risk 2) | Retrieved chunk IDs are logged with every output, so what was retrieved is inspectable rather than inferred. Confidence is composed from retrieval similarity *and* model self-confidence, and abstention fires when **either** is below threshold. A retrieval top-1 below threshold is written into the run notes |
| 3 | **Form misalignment** — pre-fill fails on a real portal | Demo restricted to a self-contained simulated HTML form; the banner "Prototype – not for live sites" is rendered on every launch and is also stored in `form_schema.json` |
| 4 | **Data leakage** — a real résumé is imported | In-memory only, no persistence. The run log stores **hashes and character counts**, never raw text — enforced by the logger, not by convention. All demonstration data is synthetic. The repository ships with a launch banner |
| 5 | **Prompt injection via the pasted JD** (OWASP LLM01) | Instruction-hijack patterns are redacted before the text reaches the model, and both inputs are wrapped in data fences with an explicit rule that instructions inside them are data. **One line, as instructed: LLM01 is a fair risk because the JD is untrusted text, but nothing auto-submits and nothing persists, so the blast radius is a bad suggestion.** The course's own framing is that there is no clean control — so the mitigation is to narrow what the model can reach, not to claim a filter |
| 6 | **Unbounded consumption** (OWASP LLM06) — a crafted input makes one case cost many times the normal | Every case has a fixed call count (3), `max_tokens` is capped in config, retries are capped at 2, and inputs are truncated at 20 000 characters. There is no loop, so there is no step cap to need. A single case costs $0.0007 (§11) |
| 7 | **Over-trust in the confidence number** | The interface shows the *reason* for an abstention, not only a score; the report states that the score is not calibrated against expert judgement (§12); the confidence components are logged separately so the composite can be decomposed |

### The silent failure, named precisely

Class 6's two-question diagnostic, run on my own components:

| Component | Wrong, will anything tell me? | Wrong, can I undo it? | Control |
|---|---|---|---|
| Retrieval | No — a bad chunk produces a fluent answer | Yes — it is text | Monitor: log chunk IDs, verify the top-1 score |
| Generation (match report) | No — confabulation arrives in the correct register | Yes — it is a suggestion | Monitor: the fabrication guard + a human reads it |
| Prefill → form | No | Yes — the user clicks Fill per field | Gate: explicit per-field confirmation |

**Nothing in this system is irreversible, and that is a design decision rather
than an accident.** The dangerous quadrant is *invisible and irreversible* — "a
silent model wired to an automatic action" — and the way to stay out of it is to
remove the wire. There is no send button, no auto-submit, and no write to any
external system. The consequence is that this is deliberately a **drafter**, not
an agent. The course frames that as a real cost with a real product decision
behind it; here the cost is that the system cannot complete an application for
Wei Ling, only prepare it.

**The silent failure I would actually expect in production**: a JD whose real
requirements are implied rather than stated. Then retrieval can look fine, the
match report reads fluently, and the system never knows it missed a requirement —
because the requirement was never in the text it was shown. §10 shows this
happens: coverage is 1/20 for every condition including the model-driven ones.

### Human-in-the-loop, stated properly

Class 6 requires all three of **window**, **evidence** and **authority**; two out
of three is a record, not a control. Here: the **window** is however long Wei
Ling takes to read the suggestion before clicking Fill; the **evidence** is the
suggested value plus the abstention reason shown beside it; the **authority** is
that she can edit, ignore or clear any field. Automation bias still applies — a
user who accepts twenty correct suggestions in a row will start clicking through
— which is why a low-confidence field is withheld rather than shown greyed out.

### Frameworks, named precisely

- **Singapore IMDA Model AI Governance Framework** — aligned in practice; and
  stated honestly, **nothing in the framework obliges anyone**. What binds in
  Singapore is the **PDPA** underneath it, plus the PDPC's 2024 advisory
  guidelines for AI recommendation systems. A soft AI layer over a hard
  data-and-sector layer.
- **OWASP Top 10 for LLM Applications (2025/2026)** — LLM01 (prompt injection),
  LLM06 (unbounded consumption). Both are addressed above. I have deliberately
  *not* claimed LLM03 (excessive agency) as a mitigation, because the honest
  position is that this system has no agency to be excessive.
- **The lethal trifecta** — private data + untrusted content + external comms.
  This system holds **two of three**: private candidate data (in memory) and
  untrusted content (the pasted JD). It has **no external-comms leg**. That leg
  is the one to drop, and dropping it is what turns an agent into a drafter. Had
  a "send" tool been in scope, the OWASP position is that there is no reliable
  prevention, so the only real control is narrowing what the model can reach.
- **EU AI Act** — not engaged: the system is not placed on the market, and its
  Annex III standalone high-risk obligations were delayed to December 2027 by
  Regulation (EU) 2026/1744.

### Intended use and explicit non-use

**Intended:** a résumé *reference and practice* tool for graduates, run locally
on synthetic or self-supplied data, whose output is suggestions a human confirms
one field at a time. Plus, as coursework, a worked demonstration that abstention
can be designed, implemented and measured.

**Explicit non-use:** not for real job submissions; not for generating
fictitious work history; not for automated form submission; **not to be pointed
at real candidate data** in its current state; not for decisions about a person
by anyone other than that person. This repository publishes no real-person data
and no model weights.

## 9 · Smallest first version

**The slice actually built first** — one input → one model call → one output,
with nothing alongside it:

> Paste a JD and a résumé → retrieve → **one** model call → print the match
> score and up to three suggestion bullets. No prefill, no form, no UI.

That slice existed and ran before the confidence rule was added. The sequence was
deliberate: the slice first, then the guard, then the abstention rule, then the
form. Everything after that is an extension of something that already ran.

**A date is not a version, so:** the slice is characterised by **three
components and no more** — a text input, a retrieval step, and a printed result.
Its boundary is that it had no persistence, no second model, no UI and no
threshold logic.

**The one sentence that tells me it worked, and how it was tested:**

> The slice works if the printed match report names only skills that appear in
> the résumé text, and at least one JD requirement the résumé does not evidence.

It was tested on three real internship JDs fetched from public portals (not used
in the knowledge base and not in the evaluation set) and checked by eye — a
qualitative sanity check, **not** part of the formal evaluation, which is what
the Problem Statement said it would be. That check is what surfaced the very
first prompt problem: the model would happily list a requirement as "matched"
because the JD mentioned it, so the "only skills in the résumé" half of the
sentence failed on the first JD I opened.

## 10 · Results — the live A/B/C evaluation

**What was run.** Run `run-20260925-123027`, mode `live_api`, model
`openai/gpt-4o-mini` over OpenRouter. 20 cases × 3 conditions = 60 records,
**0 errors**, ≈9 minutes wall-clock. Retrieval: `chroma` +
`sentence-transformers/all-MiniLM-L6-v2`, loaded from the vendored copy in
`vendor/models/` — that is, **semantic**, with the similarity scale re-derived on
that backend at percentile anchors (§10.5). The corpus is KB v2 (§6).

Four things differ from the previous revision's run, and §10.9 accounts for each
one separately: the embedding backend, the corpus, two prompt-contract fixes, and
two scoring rules that were corrected **after** the run by recomputing it from
its own log. Everything below is recomputed from `artifacts/kbv2_final/runs.jsonl`
by `report/analyse_run.py`; no number is carried over from a previous run or from
the offline stub.

### 10.1 Headline, counts first

| Condition | Passed | Complete coverage | Mean coverage | Zero fabrication | Prefill all-match | Declined | Mean confidence |
|---|---|---|---|---|---|---|---|
| **A** — rule-based TF-IDF baseline | **12/20** | 1/20 | 0.792 | 20/20 | 13/20 | 3/20 | 0.732 |
| **B** — prompt-only LLM | **17/20** | 1/20 | 0.810 | 20/20 | 17/20 | 0/20 | 0.730 |
| **C** — RAG-enhanced | **16/20** | 1/20 | 0.810 | 20/20 | 17/20 | 1/20 | 0.754 |

`Declined` is a separate column from `Passed` on purpose, and for A the two
differ: A's prefill extraction is right on 13 cases but one of those 13 is a case
A then **declined to deliver**, so it is not a completed task. `Passed` means
"delivered output that is correct", which is the PS §9 reading, and §10.9
explains why this cost two cases — one from A, one from C — relative to the
numbers in the previous revision of this report.

Coverage is quoted both ways deliberately: the all-or-nothing count (`1/20`) is
the form `passed` requires, and the mean fraction is reported beside it — 0.792
for A and **0.810** for both model conditions. **Completeness is also the one cell
in this table that is not perfectly reproducible:** C's count is 1/20 here and
2/20 in the repeat run of §10.6, where every other cell in the table repeats
exactly. A metric whose value is 1 or 2 out of 20 is a flag, not a measurement,
and §12.1 treats it as one.

**Pass bar = 16/20. B and C clear it; A does not.** On identical records and
identical scoring rules, the prompt-only model gains 5 cases over the TF-IDF
baseline (12 → 17) and the RAG condition gains 4 (12 → 16), so on this set the
retrieval layer is worth **one case less than not having it**. Stated without
decoration: with this corpus, this embedder and this prompt, the cheapest model
configuration is the best one.

**C does not beat B, and that is the finding.** Both are within one case, both
fail on the same three `top_skills` cases, and C costs **12% more** for its extra
case *fewer* ($0.0154 vs $0.0137, §11). The retrieval layer still has not earned
its keep on the metric the course asks for, and §7's kill condition — *if C does
not beat A on fabrication and coverage, the retrieval layer is not earning its
keep* — fires for exactly the reason it did before: C ties A on both (20/20
zero-fabrication, 1/20 coverage). What is new is that the excuse is gone. The
embedder is semantic, the corpus is public material, and the retrieval signal is
no longer degenerate. The layer still does not move the outcome.

The four findings that matter, in order of how much they should change someone's
mind:

**(1) Retrieval is now genuinely semantic and it still does not change the
outcome.** §7 committed in advance: *if C does not beat A on fabrication and
coverage, the retrieval layer is not earning its keep*. C ties A on both — 20/20
zero-fabrication, 1/20 coverage — so the kill condition fires exactly as before.
What has changed is the *reason* available to me. The previous revision could say
"the embedder was lexical, so C was never given the mechanism RAG exists to
provide." That excuse is now closed: the embedder is `all-MiniLM-L6-v2`, the
calibrated score takes 16 distinct values instead of collapsing to 1.000 on three
quarters of the set (§10.5), and one of the two false abstentions is gone. A
cleaner signal produced the same verdict. I report the finding as "**retrieval as
configured adds nothing measurable**", and the honest explanation is narrower than
"RAG cannot help": **this synthetic set contains no query that requires synonym
bridging.** Every JD in it names its skills outright, so the right chunk is
already reachable by keyword. §12.1 names the experiment that would settle it,
and it is not "try a better embedder" — it is "find a set where lexical matching
genuinely fails".

**(2) The abstention mechanism is better calibrated and still not demonstrated to
be useful.** The course asks for both numbers — how often the system declines,
and whether the declined cases were the ones it would have got wrong:

| Condition | Declined | On hard cases (correct) | On easy cases (false) |
|---|---|---|---|
| A | 3/20 | 3/5 | 0/15 |
| B | 0/20 | 0/5 | 0/15 |
| C | 1/20 | 0/5 | **1/15** |

B never declines, including on all five hard cases. That is not a virtue: a
system that answers every time has no safety mechanism at all, and its confidence
never fell below 0.60 in 20 cases. C declines exactly once, and it is the wrong
once — `Software_Engineering-v04_sparse_verbose-p03`, skill overlap 0.78, an easy
case, where C's combined score was 0.508 and the model's own confidence was 0.70,
but the retrieval component came in at **0.381** and the *either-component* rule
vetoed. **So C's abstention record is 0 for 1:** it has not yet declined a case it
would have got wrong. Read against the lexical run's 1-for-3 that looks like a
regression, and in the sense that matters it is — the re-calibration removed two
wrong declensions and the one right declension with them. §12.4 keeps this as an
open item rather than a claim.

**(3) `top_skills` is the dominant failure mode, and the prompt fix cut it by two
thirds.** Every failure of B and C is a `top_skills` miss, and both fail on the
*same three cases* — down from 5 and 6 on the lexical run, which is the direction
§10.7 predicted. What is left is not one cause but three different ones, which is
why the previous revision's estimate of the gain was 2× too high:

| Case | Model returned | Pool held | Sub-mode |
|---|---|---|---|
| `AIML-v04_sparse_verbose-p03` | `deep learning`, `SQL` | `Deep Learning`, `Model Evaluation`, `SQL` | **under-filled** — a required skill not named |
| `SE-v05_medium_plain-p06` | `Git`, `SQL` | `Git`, `REST APIs`, `SQL` | **slot spent on a fabrication** — the third entry was `Java`, dropped by the guard (§10.4) |
| `PM-v05_medium_plain-p06` | `Agile`, `Excel`, `stakeholder management` | `Agile`, `Excel` | **over-filled** — a skill the candidate has but this posting does not ask for |

`expected_top_skills` is the pool of skills that are both (a) in the candidate's
profile and (b) required **or clearly implied** by the JD, and a case matches only
when the returned set is **exactly the expected size and a subset of the pool**
(`src/evaluation/metrics.py`). The prompt now states the contract outright —
*"`top_skills` fills a field on an application for THIS posting … Cross-reference
the candidate's skills against the TARGET JOB DESCRIPTION and keep only those the
posting requires or clearly implies"* — and it moved the field from 15/20 and
14/20 to **17/20 for both conditions**. The residual three failures are not
specification ambiguity: they are a miscount, a fabrication, and one extra skill.
That is the honest boundary of what a prompt change can buy, and it is why §12.4
does not ask for another prompt change.

This also explains the baseline's remaining edge, and it is unchanged from the
previous revision: A ranks skills by literal overlap with the posting's
requirements, so it is *structurally incapable* of picking outside the pool. A
scores 18/20 against B's and C's 17/20 — an advantage conferred by the metric's
definition as much as by extraction quality. Reported rather than banked.

**(4) Nothing is fabricated, and the claim that would have broken that is caught
on the prefill path now.** Zero invented skills reached the output in all 60
records. The claim that came closest is `Java`, on a résumé whose skills are
Python, JavaScript, Git, REST APIs, SQL and Excel — proposed by **both B and C**
on `SE-v05` in this run, and dropped by the prefill guard before it reached the
form (§10.4). A defect being caught is not a clean sheet: Appendix A.5 is about
the fact that this same substring rule had already been fixed once on the other
guard and was still live here.

### 10.2 Failures, named

Counts hide which cases fail and why, so here are all of them.

**A — 8 not passing.** Six are `education_school` extraction misses: all four
`sparse_formal` variants plus two `medium_plain` ones (`AIML-v02`, `AIML-v05`,
`SE-v02`, `SE-v05`, `DA-v02`, `PM-v02`). Two failures (`AIML-v04`, `SE-v05`) also
carry a `top_skills` miss. The eighth is `PM-v05`, and it is the one the scoring
correction moved: A **declined** it, and the previous rule credited a declined
case as a pass whenever its raw extraction happened to be right. **The school
regex is the baseline's real weakness** — six of its eight misses — and it is a
nameable, fixable one: `sparse_formal` writes the institution in a form the
pattern does not reach.

**B — 3 not passing.** All three are `top_skills` misses and none is an
abstention: `AIML-v04`, `SE-v05`, `PM-v05`. This is the cleanest result in the
report: the prompt-only model gets every *literal* field right on all 20 cases —
`education_school` 20/20 against A's 14/20 — and disagrees only about skill
*relevance*.

**C — 4 not passing.** The same three `top_skills` misses as B, plus
`SE-v04_sparse_verbose-p03`, which C **declined**. That abstention is why C is
one case behind B rather than level with it: the case is easy (overlap 0.78), the
system computed its fields correctly, and it then withheld them — so under a
delivered-output reading it is not a completed task. That is §10.4's
proposed-versus-displayed distinction applied to the headline.

### 10.3 Per-field prefill exact match, and what each field is worth

| Field | A | B | C | Is it evidence of quality? |
|---|---|---|---|---|
| `full_name` | 20/20 | 20/20 | 20/20 | **No** — echoable from the résumé header |
| `email` | 20/20 | 20/20 | 20/20 | **No** — same |
| `education_school` | 14/20 | 20/20 | 20/20 | Yes — A's regex misses it 6 times |
| `top_skills` | 18/20 | 17/20 | 17/20 | Yes, but A's edge is circular (§10.1.3) |

Two fields are saturated and two are not, and the saturated pair is exactly the
pair a one-line regex could satisfy. This is why §6 refuses to report the prefill
metric as a single number: averaging 20/20 fields with discriminating ones would
let a trivial extractor inherit credit for work it did not do.

**One caveat, stated so this table is not read as five clean columns.** It scores
the extraction the system *computed*, including two cases it then declined to
deliver (A's `PM-v05`, C's `SE-v04`). That is the right question for a table about
extractor quality and the wrong question for the pass count, which is why
`Passed` in §10.1 also requires that nothing was declined. The two readings differ
by exactly those two cells: on delivered output only, A's `top_skills` is 17/20
and C's is 16/20.

### 10.4 Two guards, measured in both directions

The fabrication guard runs on the *match* payload; `FabricationGuard` runs on the
*form* payload. They are separate code paths with separate rules, and the run log
now records both directions for each — which is how the second one's activity
became visible at all.

| Guard | Direction | A | B | C |
|---|---|---|---|---|
| Fabrication (match payload) | model-proposed and stripped | — (no model) | 0 | 0 |
| Fabrication (match payload) | displayed as fact | 0 | 0 | 0 |
| `FabricationGuard` (form payload) | ungrounded value dropped | 0 | **1** (`Java`) | **1** (`Java`) |
| `FabricationGuard` (form payload) | displayed as fact | 0 | 0 | 0 |

Two things are worth separating. First, the *proposed versus displayed* split is
the point: scoring the model's raw proposal would report two fabrications here;
scoring what the system showed the user reports zero, and the guard's action stays
visible in the log as `notes`. Second, the one hit is the same claim on the same
case for both conditions — the model proposed `Java`, the guard removed it, and
the case still fails `top_skills` for a different reason (§10.1.3), because
removing the fabrication leaves only two of the three required skills.

**Why this is not the same as last time.** On the lexical run this claim was
*displayed*, because `FabricationGuard` used a plain substring test and
`java` matched `javascript` (Appendix A.2). That fix had been applied to the other
guard and not to this one (Appendix A.5). The distinction between the two rows is
therefore load-bearing in both directions: the guard is what keeps the
fabrication out of the product, and the log is what shows it was ever proposed.

### 10.5 The retrieval signal, after re-calibration

The calibrator rescales raw cosine onto [0,1]:
`similarity = clip((cosine − floor) / (ceiling − floor), 0, 1)`. Both anchors are
percentiles of a 100-probe separation study run on the semantic backend
(`scripts/calibrate_similarity.py`, fixed seed 20260824): **floor = p10 of the
best-hit-from-an-irrelevant-family distribution = 0.3663**, **ceiling = p90 of the
relevant distribution = 0.5633**. The band is **0.197** wide. On the delivered
run, C's top-1 calibrated similarity over the 20 cases is:

| Range | < 0.40 | 0.40–0.59 | 0.60–0.79 | 0.80–0.99 | **1.000** |
|---|---|---|---|---|---|
| Cases | 1 | 2 | 5 | 7 | **5** |

Five of twenty sit at 1.000, one falls below 0.4, and the rest are spread
continuously — **16 distinct values in total**, against five on the lexical run.
The retrieval score now ranks cases rather than flagging them, and 21 distinct
chunks were retrieved across the 20 queries with a spread of 75 O*NET / 3 ESCO / 2
guidance chunks, so the corpus is genuinely being searched rather than one generic
chunk answering everything.

**The scale change is a fix and it is a partial one.** The previous revision
anchored at the two *medians*, which is a 0.043-wide band: anything above the
ceiling pinned to 1.000 (15 of 20 cases) and anything below the floor clipped to
0.000, which vetoed a perfect match. Percentile anchors widen the band by a factor
of 4.6, and one useful property falls out — **the 0.4 abstention threshold now
sits at raw cosine 0.445, which is the median of the wrong-family distribution
(0.4434).** The system declines when a retrieval is no better than a typical
wrong-subject retrieval, which is a sentence that survives being read aloud.

**What no rescaling can fix, and I checked rather than assumed.** The two probe
distributions still overlap: **p95 of the irrelevant-family best hits is 0.5205
against a relevant median of 0.5054**. A monotone rescaling cannot turn that into
a strong confidence component, because on some queries a wrong-subject chunk
genuinely outranks a right-subject one. That is why §12.1 keeps "retrieval
similarity is a weak confidence component" on the limitations list even though the
degeneracy is gone, and why the either-component rule is now conservative rather
than arbitrary. The calibrator prints the diagnostic on every run
(`overlap_diagnostic: p95(irrelevant) > median(relevant)`), and **no evaluation
case or ground-truth label is read by the calibration**, so it cannot be fitted to
the test set.

### 10.6 Is the headline stable? Two runs of the same pipeline

The same configuration was run twice against the same 20 cases: `run-20260925-123027`
(delivered) and `run-20260925-124706` (repeat). Both use KB v2, the semantic embedder
and the corrected prompts; the only thing that differs is when they ran. Headline
counts:

| | A | B | C |
|---|---|---|---|
| Delivered (`…123027`) | 12/20 | 17/20 | 16/20 |
| Repeat (`…124706`) | 12/20 | 17/20 | 16/20 |

**Not one pass verdict moved.** Across all 60 case-condition records the
same cases passed and failed; the abstention decisions are identical
(A 3, B 0, C 1); and every per-field prefill verdict —
`full_name`, `email`, `education_school`, `top_skills` — is identical.
**Exactly one cell in 60 flipped: C's `complete_coverage` on `AIML-v01_sparse_terse-p00`** (false → true), which is why the complete-coverage column reads 1/20 in the delivered run and 2/20 in the repeat.

That is a materially stronger stability result than the previous revision could
report, and the difference is worth naming rather than celebrating. On the lexical
pair, **5 of the 60 case-condition records differed, every one of them on
`top_skills`; on 4 of those the record's pass verdict went with it, 9 verdict
changes in all**. The field that was
flaky is now the field with a written contract: the prompt states that the answer is
a set of skills *this posting* requires, sized to it, and the model returns the same
set on both runs. I would not claim the contract *caused* the variance reduction
without a third run — one comparison cannot separate a prompt effect from a
`gpt-4o-mini` sampling effect — but the flaky field is now stable, and the mechanism
is at least consistent with the prompt being the reason.

**What this does not fix.** C sits at 16/20 against a bar of 16/20, so a single
flipped case would move it below. Stability means the *estimate* is reproducible, not
that the *margin* is comfortable, and §12.1 keeps n=20 on the limitations list for
exactly that reason. The 40-case instrument in §10.8 is the answer to margin, not to
variance.

### 10.7 What would change my mind — and what already did

The previous revision of this report wrote three falsifiable predictions into
§10.7. All three have now been tested, and the honest scorecard is two and a half
out of three:

| Prediction (previous revision) | Outcome |
|---|---|
| **Semantic retrieval** would narrow or reverse the B-vs-C gap, because C had been denied synonym bridging | **Half right.** Retrieval stopped being degenerate (5 → 16 distinct values, §10.5) and one false declension disappeared, but C's pass count did not move because of it. The gap was never mainly about the embedder. |
| **A stated `top_skills` contract** would gain B and C roughly 5 and 6 cases, putting both above the bar | **Right in direction, wrong in size.** B gained 2 and C gained 3 (§10.9); both are above the bar, but not by the predicted margin. The estimate assumed every `top_skills` miss was the same ambiguity, and three of the residual ones are not (§10.1.3). It was an upper bound and it was high by about 2×. |
| **A larger set** would be a different instrument, not a bigger one (§10.8) | **Held.** Verified by regenerating both sets and comparing the difficulty profiles. |

The lesson I would carry forward is about the *size* of a prediction rather than
its direction. *"Every failure is this one cause"* is what made the estimate 2×
too high, and the only thing that revealed it was running the experiment and
looking at which three cases still failed. A prediction that is directionally
right and numerically wrong is still a prediction that was wrong, and the report
that graded it should say so.

**What would change my mind now, in order of cost:**

- **A test set where lexical retrieval genuinely fails.** C cannot show an
  advantage on a set whose every requirement is named outright. A paraphrase-heavy
  or synonym-heavy posting set is the experiment that would settle whether
  retrieval can help at all (§12.1).
- **A second model.** If B's and C's `top_skills` failures persist across models,
  the residual is a task property; if they do not, it is a `gpt-4o-mini` trait.
- **A 40-case run with the same fixes**, which would test whether the two model
  conditions stay above the bar under a harder difficulty profile (§10.8).

### 10.8 The 40-case alternative, executed

Milestone-1 feedback offered a fork: "report counts rather than percentages, or
get to 40". I took the counts branch, so the 40-case set is not the basis of any
claim above. I did run the generator's 40-case path to check it exists rather than
assert it (in a throwaway copy of the repository, so the delivered `data/` is
untouched):

| | n=20 (used) | n=40 (available) |
|---|---|---|
| Cases | 20 (5 per family) | 40 (10 per family) |
| Skill overlap | min 0.20, **median 0.86**, max 1.00 | min 0.08, **median 0.50**, max 1.00 |
| Hard cases | 5/20 (25%) | 18/40 (45%) |
| Cases with no implied requirement (coverage ceiling) | 1/20 (5%) | 10/40 (25%) |
| Regenerating is byte-identical | yes | yes |

**These two sets are not interchangeable, and that is worth knowing.** The extra
20 profiles are substantially weaker, so the 40-case set is harder, its coverage
ceiling is five times higher, and its expected abstention rate would break the
abstention ceiling. Switching to it would silently change every conclusion. Had I
run 40 cases and reported the result as "the same test, bigger", that would have
been wrong; the honest statement is that the delivered results are the n=20 set
and the n=40 set is a different, harder instrument.

### 10.9 What each change can be credited with, and what is not separated

Four things changed between the lexical run quoted in the previous revision of
this report and the run above, plus two scoring corrections applied afterwards by
recomputation. The honest accounting is a table with an empty column, because one
attribution genuinely was not measured.

| Change | What it demonstrably moved | What it cannot be credited with |
|---|---|---|
| Prompt contract: `top_skills` defined against the target posting | The field's misses fell from 5 and 6 cases to 3 and 3; the two model conditions went from below the bar to above it | The share of the gain that belongs to the other prompt fix — both touch the same field |
| Prompt contract: enumerate requirements the JD *implies* through its duties | JD-required coverage: the parser now adds skills the posting implies without naming | The verdict. Coverage is still 1/20 complete for every condition, so this moved the mean, not the conclusion |
| Corpus v2 (O*NET/ESCO/ATS instead of project paraphrase) | Retrieval separation, **+0.0429 → +0.0621** (§10.5) | **Not attributable on its own.** No run exists with the v2 corpus on the lexical embedder, nor v1 on the semantic one |
| Semantic embedder (`all-MiniLM-L6-v2`, vendored) | The calibrated score stopped being binary (5 → 16 distinct values); the 0.4 threshold acquired a defensible meaning; false declensions 2 → 1 | **Not a higher score.** C's pass count is unchanged by it, and the one *correct* declension disappeared with the false ones |
| Scoring: a declined case can no longer count as a pass | A 13 → 12, C 17 → 16 | Nothing about the model. It corrected arithmetic over output the model had already produced |
| Scoring: `metrics.csv` stopped hard-coding a zero-width pass bar | `meets_pass_bar` now reads 0 for A instead of a constant 1 | Nothing. It was a reporting bug that made the shipped CSV wrong about its own numbers |

**Read the corpus row carefully.** The corpus and the embedder were changed in
the same step, because the similarity calibration is fitted to the *pair* and
re-fitting was unavoidable. That means the corpus's contribution is **not
isolated**, and I am not going to credit the O*NET sourcing for the +0.019
separation gain when a different embedder is also in the loop. The run that would
separate them is the v2 corpus with `--embedding-backend tfidf`: the files are in
the repository, the flag is supported, and it costs about $0.03. **It was not
run**, and §12.1 says so rather than letting the table imply an attribution that
was never measured.

**And a correction to the headline itself, since the previous revision of this
report printed different numbers.** It reported A 13 / B 15 / C 14. Three of those
digits moved for three different reasons: A's 13 → 12 is the scoring fix alone
(one declined case was being credited); B's 15 → 17 is the two prompt fixes and
the corpus/embedder change; C's 14 → 16 is the same gains minus the one case the
scoring fix removed. Anyone comparing the two documents should not read the
change as "the system improved by 2–3 cases" — a large part of it is two errors in
my own scoring code being removed, which made the *previous* numbers too
generous, not this one too harsh.

**And the one lever §11 names is not in this table at all, because it was never
built.** `report/router_design_note.md` works through the field-level rule/model
router that §10.1's finding (3) and §11's lever 2 both point at: what it would
dispatch on, the ceiling its per-field counts imply, and why this round's decision
was to leave it unbuilt. Every figure in that note is derived from this section's
own per-field counts rather than from a run, and the note labels it that way
throughout.

## 11 · What it costs

Prices use OpenRouter's published per-token rates for `gpt-4o-mini` as
configured, applied to the token counts the API returned. Every figure is the sum
over the delivered run of 20 cases.

| | A | B | C |
|---|---|---|---|
| Model calls | 0 | 60 | 60 |
| Input tokens | 0 | 47,965 | 58,971 |
| Output tokens | 0 | 10,916 | 10,967 |
| Cost, 20 cases | **$0.0000** | **$0.0137** | **$0.0154** |
| Cost per case | $0.0000 | $0.0007 | $0.0008 |
| Median latency per case | 16 ms | 8,289 ms | 8,375 ms |
| Worst-case latency | 42 ms | 10,876 ms | 10,466 ms |
| **Cost per successful task** | **$0.0000** | **$0.0008** | **$0.0010** |

**The interesting number is the last row, not the token bill.** Cost per
*successful* task (Class 5's measure — the variable cost divided by the cases that
actually passed) is $0.0008 for B and $0.0010 for C. **C spends 12% more than B
and delivers one fewer success**, so its cost per success is 19% higher on the
same 20 cases. At these prices the token bill is not the constraint: **the whole
20-case evaluation cost $0.0291**, and a single case costs less than a thousandth
of a dollar.

The real costs are elsewhere, and the course's own framing (Class 5/C2) is that
cost-to-serve also contains retries, human review, integration, monitoring and
maintenance. Concretely, for this system:

- **Latency dominates.** A median of ~8.3 seconds per case is about 500× the
  baseline's 16 ms, and the worst case ran just over ten seconds. For Wei Ling
  that is a spinner she waits through; for the design it means the 3-call pipeline
  is what a user experiences, not the model's intelligence. Note that this is
  unchanged by any of the work in §10.9: the retrieval step adds 11,006 input
  tokens and about 90 ms, and it is the three sequential model calls that cost the
  seconds.
- **Human review is the largest cost and it is not in any table above.** Eight
  form fields × one click each, plus reading the match reasons. That is minutes
  of attention per application, against a system whose marginal cash cost is
  $0.001. Any argument for this tool has to be won on the human minutes it saves,
  which is exactly the claim the instructor told me not to make on one timer.
- **Time-to-deploy, honestly.** I did not instrument total build time, so I will
  not invent a figure. The one datapoint I do have is the n8n attempt: two hours,
  reported in §5 for the reason it broke, not as a build-time estimate.

**Break-even, so the answer comes with one (Class 5/C2).** Against a $49.95/month
vendor subscription (§2), the model cost breaks even at
$49.95 ÷ $0.0010 ≈ **50,000 successful tasks per month** — a volume no individual
job-seeker will approach. The conclusion is not that the subscription is
expensive; it is that **at this scale, cost is not the axis of competition**. The
subscription buys a polished product, not compute. Building this earns its keep
through abstention, provenance and data control, or it does not earn it at all.

**Levers, in the course's order** (success rate ≫ routing ≫ caching ≫ batch ≫
observation size ≫ move work to code), applied to what §10 measured:

1. **Success rate first** — and §10 says the lever is the `top_skills` contract,
   not the model. Nothing else is worth touching until that is fixed.
2. **Routing** is the one with a demonstrated pay-off here, and §10.9 has now
   removed the reason it was second: A and the model conditions fail on
   *disjoint* causes (A on `education_school`, six of its eight misses; B and C
   only on `top_skills`), and A is free. A router that sent the school-regex cases
   to the model and the rest to A would beat either condition alone on this set.
   That is the strongest product argument in the report, and I still have not
   built it. `report/router_design_note.md` works the claim through instead of
   leaving it as an assertion: the ceiling its per-field counts imply is 18/20,
   one case above B, and the sign of that single case turns on who owns the
   case-level decline decision - so the note states the gain as *at most one
   case* rather than as a win. §11's own standard applies to it: at n=20 one case
   is 5 points, and the report already refuses to read a one-case gap as a
   verdict.
3. **Caching** is irrelevant — every case is a distinct résumé/JD pair.
4. **Observation size** — C's retrieved chunks are +11,006 input tokens (23%)
   over B, and on this set they changed no verdict. Removing them is the cheapest
   possible change and it is what dropping to condition B amounts to.
5. **Move work to code** — already done where it matters: the score, the
   validation and the abstention decision are all in code (§4), which is why A
   costs nothing.

## 12 · Limitations, reflection, and what this does not show

### 12.1 What the results do not show

| Limitation | Why it matters | What would settle it |
|---|---|---|
| **Retrieval similarity is a weak confidence component** | The degeneracy is fixed (§10.5) but the two probe distributions still overlap — p95 irrelevant 0.5205 > relevant median 0.5054 — so a high score is not strong evidence, and the either-component rule stays conservative. | a retrieval task where the relevant chunk is *not* lexically close: a paraphrase-heavy posting set, or a real corpus |
| **The corpus and the embedder changed together** | Their contributions cannot be separated, so §10.9 leaves the +0.019 separation gain unattributed rather than crediting the O*NET sourcing for it. | the v2 corpus with `--embedding-backend tfidf` on the committed files; about $0.03, and not run |
| **n = 20** | one case is 5 points, and C sits exactly on the bar; §10.6 shows the estimate is reproducible but the margin is one case | the 40-case generator, noting §10.8: it is harder, not merely larger |
| **Synthetic résumés and JDs** | the ceiling §6 names applies: data generated from one model's schema inherits that model's blind spots, and real postings are messier and longer | real postings with the candidate's own résumé, with consent |
| **`match_score` is never validated** | it is logged, not scored, and nothing in this report depends on it — but a reader should not read the 45–85 numbers in the console as calibrated | expert ranking vs the score, on the same cases |
| **No counterfactual, no online measurement** | a fixed test set measures nothing about whether Wei Ling's *outcomes* improve | a deployment with an override/re-open-rate signal (Class 6/C1: the cheapest drift signal) |
| **The 30% time-saving metric is unmeasured** | disclosed in §7 and priced in §11; it needs ≥3 independent timers and there is no `data/timing/` file | three timers, both phases, same cases — then `timing.enabled: true` |
| **One model, one temperature** | nothing here says whether the `top_skills` disagreement is a `gpt-4o-mini` trait or general | repeat §10 with a second model |

### 12.2 Where the ground truth could be fooling me

The Watch-outs ask for the score before and after hunting leakage, and for the
ground truth to be fixed before inference. Both were done; here is what the hunt
found, including the parts that remain uncomfortable.

- **Ground truth was frozen before any inference ran**, and is regenerated
  byte-identically (§6). It is read by the scorer and written only by the
  generator.
- **No label reaches the pipeline.** `run_case()` receives `resume_text` and
  `jd_text` and nothing else; `job_family` and `variant` are logged, and a test
  asserts that the parameter list contains no ground-truth field (§6).
- **Condition A's abstention record is circular, and it is reported as circular
  in every place it appears.** A's confidence *is* lexical skill overlap, and
  "hard case" *is* overlap < 0.5, so A's 3/5 is not independent evidence. The
  labels never enter the pipeline, but the two quantities share a parent
  statistic.
- **A's `top_skills` advantage is circular** for the same reason: the field is
  scored against a pool defined by JD-required skills, and A selects by literal
  overlap with JD-required skills (§10.1.3).
- **Two fields are saturated and uninformative.** `full_name` and `email` are
  20/20 for every condition, including a regex. They are reported per field
  rather than averaged for precisely this reason.
- **A defect in the ground-truth generator's own contract was found twice during
  development** (`Deep Learning` implying `Machine Learning`; "Master of Science"
  leaking in as a skill). Both were caught by the generator's own round-trip
  assertion, and both are in Appendix A, because a ground truth that drifts is
  the failure the Watch-outs warn about without naming.

### 12.3 Reflection — the five threads

**Paid once versus paid forever.** The model is $0.001 a case. The 54-chunk
corpus with per-chunk provenance *and a licence obligation attached to it*, the
guards' rule sets, the re-derived similarity scale and the frozen ground truth are
the assets that took the time and that a competitor calling the same API cannot
copy. §10 is the proof that the rentable
part is not where the value is: swapping in a better model cannot fix a
`top_skills` contract ambiguity.

**The model is rentable; your data and governance are not.** Confirmed
accidentally and usefully. Two runs of the identical pipeline produced different
`top_skills` verdicts on 5 of the 60 case-condition records — four of them flipping
the record's pass verdict — while the ground truth, the corpus and the calibration
were byte-identical. **The variance lived in the rented component and nowhere
else.** That is the strongest available argument for owning the measurement.

**A gate someone can operate.** The abstention gate is the product. It is also,
per §10.1, currently miscalibrated — it vetoed a perfect match. A gate that is
operable is not the same as a gate that is right, and shipping the first while
believing you have the second is exactly the failure mode Class 6 describes.

**You cannot test what you did not imagine.** I wrote a fabrication guard, tested
it against a stub, and it was green for the entire period in which it was
stripping *every* claim on the live path (Appendix A.1). The test suite could not
have caught it, because the stub returned canonical names and the model did not.
What caught it was running the real path and reading the log. Both defects in
Appendix A were found that way, and the second one — the guard's substring
matching letting `java` match `javascript` — required the metric to be
double-checked against the raw text of a single résumé. **No summary would have
surfaced it.**

**The constraint is never the algorithm.** Nothing here failed for lack of model
capability, and the second live run is the evidence for it: the change that moved
two conditions above the pass bar was a **definition of a form field**, not a
better model and not a better corpus. What remains is a miscount, one invented
skill and a regex. Two of the seven defects in Appendix A were in my own *scoring*
code — the part I had been treating as the ground against which everything else is
measured — and they were found by recomputing the run rather than by running
anything new. The largest single block of failures in the previous run (11 of 40
model-facing records) was a three-word ambiguity, *top skills of what?*, and
removing it cost 2× the prediction because I had assumed it was the only cause.

### 12.4 What I would do next, in order

The previous revision's first two items — state the `top_skills` contract, and
re-derive the retrieval scale on the semantic backend — are done (§10.9). What
replaces them, in the order I would actually do them:

1. **Separate the corpus change from the embedder change.** One run with
   `--embedding-backend tfidf` on KB v2, about $0.03 and no code change. Until it
   exists, §10.9's table has an attribution hole in it, and the hole is the row a
   reader most wants filled.
2. **Build the router.** A is free and fails on a *different* axis: six of its
   eight misses are the school regex, while B and C fail only on `top_skills`.
   §11 shows routing is the lever with a demonstrated pay-off here, and §10.9 has
   now removed the reason it was deferred.
3. **Decide whether the either-component rule earns its place.** C has declined
   once in two runs and it was wrong. Either the retrieval floor tracks the
   evidence, or the rule is replaced by a combined-score test — and the choice
   should be made on data, not on the principle that retrieval grounds answers.
4. **Move to 40 cases** — and re-baseline, because §10.8 shows it is a harder
   instrument, not a longer one.
5. **Sliced evaluation.** Class 6/C1's point that a model can be 94% and 71% right
   at once applies here: B scores 5/5 on Data Analytics and 4/5 on AI/ML. A single
   headline number hides that, and I have not reported it as a slice because n=5
   per slice is too small to conclude from.

## 13 · How the instructor feedback was applied

Every point from `feedback.docx`, verbatim where short, and what changed.

| Feedback | What I did | Where it is visible |
|---|---|---|
| "20 cases … against a 16/20 pass bar — one miss is five points. **Report counts rather than percentages**, or get to 40." | Took the counts branch. `metrics.csv` carries `x/n` as the primary form; every table in §10 is count-first; percentages appear only where a mean is needed, always beside the count. The 40-case path was then executed to check it exists (§10.8) — and it is a *different* test, which is reported rather than glossed. | §7, §10, §10.8 |
| "**The committed generator** is what makes that fixable." | The generator is committed and deterministic; regeneration is byte-identical at both n=20 and n=40. | §6, §10.8 |
| "The 30% time saving has **one timer and it is you both times** … Find three people or drop it." | Demoted out of the headline to a gated secondary metric that refuses to emit any number below 3 independent timers that each measured both phases on the same case. It also flags order-contaminated timers. The gate is exercised by tests, including the below-threshold and no-paired-case paths. | §7, §11, `src/evaluation/timing.py` |
| "**A/B/C on fabrication and skill coverage carries the claim alone.**" | These are the headline results and the only basis for the §10 conclusions. | §10.1 |
| "**1 to 6 all in.**" | The mapping is set out directly below this table; the traceability table records the deck and page for each borrowed method. | §13.1, `requirement_traceability.md` (author's working copy) |
| "**LLM01 is fair**, the JD is untrusted text — but nothing auto-submits and nothing persists. **One line.**" | One line, in the risk table, plus the mechanism (redaction + data fences) in the same cell. Not a section. | §8, risk 5 |
| Good: "You gave n8n **two hours and reported where it broke**." | Kept, with the two specific breakages named. | §5 |
| Good: "**Rejecting LLM-as-judge** for exact-match checks — right call." | Kept, together with what that decision costs (§7): exact match is brittle and §10.1.3 shows exactly where. | §7 |

### 13.1 The build mapped to the six course weeks

"1 to 6 all in" asks for coverage of the whole course, so here is what each week
contributed to this system and where it is visible. Sources are the deck names in
`study slides/`; page-level citations are in the author's `requirement_traceability.md`,
kept beside the report rather than submitted with it.

| Week | What the week is about | What this build took from it | Where it shows |
|---|---|---|---|
| **1** | What AI is; sorting versus making; a classifier returns a *calibrated probability* you can threshold, an API returns a word with no honest confidence attached | The whole justification for **constructing** a confidence signal out of two components instead of trusting a model's tone. The decision to keep the model out of arithmetic and validation is a Week-1 distinction between kinds of system. | §4, §7 |
| **2** | The 7-layer modern AI stack; build versus buy; RAG as embed → retrieve → generate; evaluations and judge alignment | The own/rent table, layer by layer (§5). RAG's three stages are the retrieval design (§4). The no-LLM-as-judge decision comes from the same week's material on judge alignment and κ. | §5, §4, §7 |
| **3** | Steer it and prove it: the prompting ladder, anti-patterns, eval-set proportions, temperature 0 so a change in pass-rate is the edit and not luck | The eval set is built 5 typical / 3 edge / 2 adversarial per family. Temperature is 0 throughout. The rung chosen is the one that addresses the failure — the fabrication instruction plus a guard in code, not "do not hallucinate" (Week 3 names that as an anti-pattern with no mechanism). | §6, §7, §8 |
| **4** | Build it and harden it: guardrails live in code not the prompt; grade the outcome not the path; "the dangerous agent is the one that is right about everything you tested" | The ablation guard, the schema checks and the threshold comparison are all code (§4). The pass condition grades the *outcome* on a frozen set with at least one negative case per family, and §10 is the evidence that the tested path was not the only one that mattered — both Appendix A defects appeared outside it. | §4, §7, §8, Appendix A |
| **5** | Where AI is worth building: the two archetypes and the two-question diagnostic; what it actually costs — cost per *successful* task, break-even, the leverage order | The archetype analysis (§4: A for the match-and-tailor step, B for the manufactured confidence) and the honest admission that Archetype A's precondition — a labelled history — does not exist here. §11 is Week 5's cost method applied: cost per successful task, a break-even, the lever order, and "more tokens ≠ more accuracy" borne out by C's +16% input tokens buying nothing. | §4, §11 |
| **6** | How each kind of AI breaks; what you owe and how it breaks — the lethal trifecta, OWASP LLM01/LLM06, governance; the frontier, the case and the course | The failure taxonomy drives §8: four kinds of failure, the two-question diagnostic applied to my own components, the silent-failure quadrant named. The governance section names what actually binds (PDPA) separately from what is voluntary (IMDA MGF). The five closing threads are §12.3. | §8, §12.3 |

The one week whose material I explicitly did **not** act on is Week 6's sliced
evaluation: B scores 3/5 and 5/5 across families, which is a slice no single
headline shows — but at n=5 per slice there is nothing to conclude from it, so it
is named in §12.4 as unfinished rather than presented as a finding.

## 14 · Reproducing every number

```bash
cd resume_jd_matcher
pip install -r requirements.txt          # pypdf, numpy, scikit-learn, chromadb, streamlit, python-dotenv, openai

# 0. the semantic embedder is vendored, not fetched at run time
ls vendor/models/all-MiniLM-L6-v2        # config.json + a non-empty weights file
python scripts/calibrate_similarity.py --write-note   # re-derives floor/ceiling

# 1. regenerate the evaluation set (deterministic; verifies the ground truth)
python -m data.synthetic_generator.generate_cases            # 20 cases
python -m data.synthetic_generator.generate_cases --n-cases 40

# 2. rebuild the knowledge base and its index (KB v2)
python -m data.knowledge_base.build_kb

# 3. the delivered live run  (needs OPENROUTER_API_KEY in .env)
python eval/run_eval.py --live --out-dir artifacts/kbv2_final
#   -> runs.jsonl, metrics.csv, case_scores.csv, report.md, kb_descriptor.json

# 3b. the repeat run used for the stability check in §10.6
python eval/run_eval.py --live --out-dir artifacts/kbv2_repeat

# 4. every number in §10 and §11, recomputed from the log, no API calls
python report/analyse_run.py --artifacts artifacts/kbv2_final
python report/analyse_run.py --artifacts artifacts/kbv2_repeat

# 4b. re-derive metrics.csv / case_scores.csv / report.md under the scoring rules
#     as they now stand (no API calls, and no rebuild of the index)
python scripts/rescore_run.py --artifacts artifacts/kbv2_final

# 5. offline plumbing check (no key, no network)
RJD_OFFLINE=1 python eval/run_eval.py --offline --fresh
RJD_OFFLINE=1 python scripts/smoke_check.py

# 6. the tests
python -m unittest discover -s tests        # 109 tests

# 7. the UI
RJD_OFFLINE=1 streamlit run app.py
```

Run identifiers for the live runs quoted in this report:
`run-20260925-123027` (delivered: semantic retrieval on KB v2) and
`run-20260925-124706` (the stability pair in §10.6). The earlier **lexical** pair
that the previous revision of this report was based on —
`run-20260924-014232` and `run-20260924-013038`, with KB v1 on a TF-IDF
embedder — is preserved under `artifacts/lexical_run/`. It is the baseline for
§10.9's comparison and the basis of **no** headline number in this document. The
intermediate semantic run in which the prefill-guard defect was still visible is
under `artifacts/kbv2_semantic/` and is the evidence for Appendix A.5.

---

## Appendix A · Defects found by running the live path

Seven defects were found in this system after its test suite was green — six in
the code and one in how I operated it. They are written up because the pattern
matters: **each one was invisible to a passing test suite.** Six were visible only
on the real path with the log read line by line; the seventh was found by
recomputing a finished run from its own log, which is a different discipline from
running it and one I had not been applying to my own scoring code.

The earlier revision of this report documented A.1–A.4. Those four are kept as
written, with A.2's outcome updated to the current run, and A.5–A.7 are new.

### A.1 The fabrication guard stripped every claim on every live call

**Symptom.** The first live probe had B and C abstaining on every case, with
`llm_self = 0.35` exactly — the value of `fabrication_cap`.

**Cause.** The guard compared the model's claimed skills against the literal
vocabulary with a raw set difference. The model answers in its own casing
(`"machine learning"`, `"natural language processing (NLP)"`) while
`match_skills` returns canonical names (`"Machine Learning"`, `"NLP"`). Every
lower-cased claim therefore looked unsupported, so the guard stripped the entire
matched-skill list and capped confidence below threshold — a systematic,
silent forced abstention.

**Why the tests missed it.** The offline stub returns canonical names, so the
comparison succeeded in every test. The bug existed only where a real model
answers.

**Fix.** Compare canonically on both sides, via a single `has_lexical_support`
predicate (which also has its own tests). The second live probe moved B from
"abstains on 20/20" to "answers at confidence 0.80".

**Also fixed:** `notes` were not persisted to the run log, so the guard's action
left no trace. That is the reason this went unnoticed for an entire live run, and
it is now a first-class field.

### A.2 `java` matched `javascript`, and the guard's effect was invisible

**Symptom.** In the first full live run C showed 1 fabrication. Inspecting it
revealed two problems in opposite directions.

**Cause 1 — under-strict fallback.** The guard's second test was a bare substring
match as a fallback for out-of-vocabulary skills. `"java"` is a substring of
`"javascript"`, so a genuine fabrication — the model claiming Java for a
candidate whose skills are Python, JavaScript, Git, REST APIs, SQL and Excel —
passed as supported.

**Cause 2 — the metric scored the wrong list.** `claimed_items` was collected
from the model's raw payload, so a claim the guard *removed* was still counted
against the system. The guard could work perfectly and the fabrication rate would
not move.

**Fix.** Word-boundary matching in the fallback (`java` no longer matches
`javascript`; `JavaScript` still matches), and `claimed_items` now holds the
post-guard lists while `stripped_claims` records what was removed. On the
lexical run the same case reported **1 stripped, 0 displayed**.

**Note added after the second live run:** that fix was applied to *one* of the two
guards. The identical substring test was still live in the other one, and it was
still letting the same claim through — Appendix A.5.

### A.3 A composite alias defeated canonicalisation

**Symptom.** After A.1, the one remaining C fabrication was
`natural language processing (NLP)`.

**Cause.** The résumé literally says `natural language processing (NLP)`, and the
ground truth lists the skill as `NLP`. `canonicalise` did exact alias lookup only,
so the parenthesised composite form fell through and matched nothing — turning a
genuinely grounded claim into a reported fabrication. This inflated the headline
that the instructor said could carry the conclusion on its own.

**Fix.** `canonicalise` now also tries the abbreviation form of a composite
(`"X (Y)" → "Y"`) and the leading phrase. Full round-trip tests were added for
composite and parenthetical forms.

### A.4 The evaluation harness corrupted its own log (run lock)

**Symptom.** A live run finished and reported A 0/0, B 7/8, C 0/20 with
`NotFoundError` on every C case.

**Cause.** Two evaluation processes were running against the same `artifacts/`
directory. Each `--fresh` truncated the other's `runs.jsonl`, and rebuilding the
Chroma store made the other process's collection vanish mid-flight. The log then
held records from two runs under two run ids, and the scoring selected one of
them — producing a table computed from a mixture. This was my operational
mistake, not a product defect, and the numbers were discarded rather than
reinterpreted.

**Fix.** `acquire_run_lock()` refuses to start a second run against the same
out-dir, clearing a stale lock only when its PID is verifiably gone. Its first
implementation was itself wrong — `tasklist` output decoded as UTF-8 raises on a
non-English Windows, which made *every* PID look dead and silently disabled the
guard — so the liveness check now decodes leniently and the guard is exercised by
tests.

### A.5 The substring fix was applied to one guard and not the other

**Symptom.** After the prompt-contract change, a fresh live run showed `Java` for
**both B and C** on `Software_Engineering-v05_medium_plain-p06`, displayed as a
fact on a résumé whose skills are Python, JavaScript, Git, REST APIs, SQL and
Excel. It looked like a regression the prompt change had caused.

**Cause.** It was not a regression; it was the same defect as A.2, still live.
There are two guards: `taxonomy.has_lexical_support` on the match payload, which
A.2 fixed, and `extractor.FabricationGuard.supports` on the form payload, which
was written independently with the same plain-substring test. Fixing one left the
other and no test covered the second. The two code paths agree on nothing except
that they both mean "is this claim grounded in the candidate's text".

This is worth stating plainly because it is a *consequence of* the earlier fix: a
defect that is fixed in one place and not in its twin is more likely to be
mistaken for a new problem than for an old one, which is exactly what happened
until the log for that one case was read line by line.

**Fix.** Word-boundary anchoring in `FabricationGuard.supports` for both the
phrase test and the per-token fallback, and a regression class
(`TestFabricationGuardWordBoundaries`, 7 cases) covering `Java ∉ JavaScript`,
multi-word phrases, punctuation and the empty case. On the current run both B and
C report the value as **dropped, 0 displayed** (§10.4).

### A.6 `passed` credited cases the system had declined

**Symptom.** Recomputing the finished run from its log produced different pass
counts from the ones the run itself had reported, and the discrepancy was exactly
the declined cases.

**Cause.** `CaseScore.passed` documented the rule "an abstained case ... cannot
pass", and the implementation did not apply it:
`return self.zero_fabrication and self.prefill_all_match`. That mattered because
of an interaction the docstring assumed away. On a decline the runner zeroes every
field confidence and replaces the suggestion list with a decline notice — so the
user sees *no* fields — but `to_record()` logs the raw extraction, and the scorer
graded the raw extraction. **The metric was crediting prefill values the system
had deliberately withheld.** Two cases in the delivered run were affected: A's
`PM-v05_medium_plain-p06` (13 → 12) and C's `SE-v04_sparse_verbose-p03`
(17 → 16).

**Why the tests missed it.** There *was* a test for this rule —
`test_abstained_case_cannot_pass` — and it passed for the wrong reason. It built an
abstained record with the four prefill fields set to empty strings, so the score
was false because the fields were empty, not because the case had abstained. It
would have gone green against an implementation that had no abstention clause at
all. The test has been rewritten to abstain while carrying correct-looking output,
which is the only version of it that tests the rule. **This is the same shape as
A.1**: a check that passes for a reason unrelated to what it names.

**Fix.** `passed` requires `not abstained`; the test uses a populated prefill and
asserts the two intermediate facts as well (`prefill_all_match` true,
`abstained` true) so a future regression cannot hide behind an empty record. The
delivered artefacts were re-derived with `scripts/rescore_run.py` rather than by
re-running the API, so the records themselves are unchanged.

### A.7 The shipped metrics.csv said every condition met the pass bar

**Symptom.** `artifacts/metrics.csv` carried `meets_pass_bar = 1` for all three
conditions, including condition A at 12/20 against a 16/20 bar.

**Cause.** The CSV writer called `as_row(0.0, 0.0)`. `as_row` derives the bar as
`round(pass_bar_fraction × n_cases)`, so a fraction of 0 makes the minimum 0 and
`passed >= 0` true for every row. The load-bearing argument was never passed in.
The console summary and `report.md` used the real fraction, so only the CSV
disagreed with the rest of the artefact — which is worse than a uniformly wrong
number, because it looks authoritative.

**Fix.** `write_metrics_csv` takes the pass-bar fraction and the abstention
ceiling and forwards them; `run_eval.py` passes the configured values. The CSV in
`artifacts/` was regenerated, and it now reads `meets_pass_bar` 0 / 1 / 1.

## Appendix B · A log field that was computed and then dropped

§7 states that `components_present` is recorded on every case so a reader can see
which components entered the confidence formula. On inspection it was not: the
`Assessment` carried it and `assessment.as_dict()` exported it, but the
`RunRecord` never copied it, so it was absent from `runs.jsonl`.

The practical consequence is exactly the misreading §7 was trying to prevent: a
condition-A record shows `llm_self_confidence: 0.0`, which reads as "the model
returned zero" rather than "there was no model", and `confidence` cannot be
reconstructed from the record. The delivered run now logs
`components_present: ["retrieval"]` for A, `["llm_self"]` for B and
`["llm_self", "retrieval"]` for C on all 20 cases each, and a test asserts that
the record — not only the in-memory assessment — carries the field. The repeat run
in §10.6 was executed partly to make this true of the delivered artefact rather
than only of the code.
