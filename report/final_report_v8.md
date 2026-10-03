# Graduate Resume–JD Matcher with RAG-Prefill Assistant

*Business case v8. First person throughout (Watchouts p.3). Every quotation carries deck and page (Watchouts p.1).*

**Keys.** `PS §N` = problem statement; `README §N` = `resume_jd_matcher/README.md`.

## 1 · Working title

**Graduate Resume–JD Matcher with RAG-Prefill Assistant.**

**Decision:** keep *prefill* in the name and keep *submit* out of it.

## 2 · The problem, and why it matters

**One sentence.** No low-cost assistant adapts a graduate's resume to a posting and fills the form *without inventing experience*. Wei Ling spends **10–15 hours a week** on applications (PS §2–§3).

| Tool | What it does | What it does not do |
|---|---|---|
| Jobscan | Reports a keyword match rate | Cannot say "I cannot support this from your data" |
| Teal | Resume tailoring tracker | Same — no abstention path |
| Rezi | Rewrites to a template | Generates confidently rather than abstains |
| Resume Worded | Scores and suggests edits | Same |

**Out of scope:** real portals, auto-submission, persistence, fine-tuning (PS §5).

**Commercial impact:** Wei Ling recovers 10–15 hours/week for interview preparation; at $0.0008 per successful task, the cost per recovered hour is under one cent.

**Decision:** a *trust* problem with a matching problem inside it, not the reverse.

## 3 · Who it is for, and the domain

**One user, by role:** the graduate job-seeker — an MSc student with no careers-office appointment and no paid subscription. *Wei Ling, at 9pm, tailoring her resume to the fourth posting of the week* (PS §3).

**Decision:** a short actionable list, and an abstention that explains itself rather than printing a number.

**What changes for her:** she reads match reasons and missing requirements instead of re-typing — and spends the recovered time on interview preparation (PS §3).

## 4 · Why AI — and which kind *(ILO 1, 3)*

**Decision: rent the model, own the rules that stop it being wrong.** (PS §4; Watchouts p.2)

**The free baseline, named.** Condition A — TF-IDF and keyword overlap, **12/20 alone** — stands in for the majority-class baseline: "the score you get by always guessing the most common answer" (Watchouts p.3).

| Rung | Bought? | What it bought |
|---|---|---|
| Prompting (Class 3) — one prompt contract | Yes | All of B and C |
| Retrieval-augmented generation (Class 2) | Yes | Grounding on a corpus I can cite, at +$0.0001 per case — and, per §10, no extra pass |
| Fine-tuning | No | Retrieval supplies the facts; no behaviour to learn |
| Agent (Class 4) | No | The path is fixed — input → retrieve → one call → one output |

"Match the type to the job, and climb the ladder only as far as you need" (Watchouts p.2) — refusing the agent was task-type matching, not caution.

**Why confidence had to be built, not read.** A classifier "returns a calibrated probability for every class ... so you can set a threshold and route anything below it to a human"; an API "returns the word 'positive', with no honest confidence attached" (C2_Sorting_vs_making p.11). The abstention gate is built from retrieval evidence and model self-report — **the mechanism that lets the system decline instead of invent** (README §5).

**Four rules stay deterministic:** PDF extraction, the abstention threshold, refusal of locked controls, and identity-document detection (README §5).

## 5 · Build vs buy *(ILO 2, 3)*

**Decision: rent the commodity, own the logic and the data.** Down the Class 2 stack — seven layers, one reason each (Watchouts p.2; PS §5):

| Layer | Own/rent | Why |
|---|---|---|
| Interface | **Build** | The interface is the product; a rented UI would own the user relationship |
| Hosting | **Neither** | One user on one machine — a cloud bill buys nothing yet |
| Model inference | **Rent** | **`openai/gpt-4o-mini` on OpenRouter** — a frontier model cannot be rented as training |
| Vector store | Rent | A commodity; a rival can buy the same one, so it decides nothing |
| Orchestration | Build | This *is* the product logic |
| Data and embeddings | Build | A rival on the same API cannot copy my corpus |
| Evaluation | Build | My risk; my rubric |

One hosted model over one gateway, at **$0.0008 (B) / $0.0010 (C)** per successful task — "Cost per SUCCESSFUL task. Always." (Class5/C2 p.26). **Low-code as evidence:** two hours on a workflow builder broke on the feature the product exists for: conditional branching on the abstention threshold. I moved to Python for control (feedback line 6).

## 6 · Data *(ILO 2)*

**Decision: a licensing-clear public corpus, one committed generator, ground truth frozen before any run.** With §7 and §9, these carry criterion 3 — "the largest single block of the project mark at 35%" (Watchouts p.1).

**The corpus is 54 chunks from public CC BY 4.0 sources.** The test set is 20 cases from one committed generator. **Ground truth is frozen before inference** — "in a file before you run anything, never after you have seen results" (Watchouts p.2). **Two reported deviations:** a document-extraction chain different from the plan with no repository reason (v4 §H.1 row 3); and condition A's abstention record being circular (README §7.4).

## 7 · Metric and evaluation *(ILO 2, 3)*

**Decision: one number to hit, a free baseline, abstention as two numbers, no LLM-as-judge.** "Accuracy without the majority-class baseline ... says nothing" (Watchouts p.3); "give your system a way to say 'I don't know' — then measure it" (Watchouts p.3).

**The metric is a pass rate over 20 fixed cases**, bar **16/20**, where a pass needs **zero fabricated skills** and an exact match (README §7.1). **Abstention is two numbers** — how often, and whether those were the cases it would have got wrong (README §7.3). **Delivered: A 3/20, B 0/20, C 1/20**; C's single abstention is false (report_en.md §10.1).

**No LLM-as-judge:** the instructor called it "right call" (feedback line 6), and "an unaligned judge just launders bias" (Class2/C4 p.13). **L1 is machine-checkable, L2 hand-judged** — "L1 checks the shape of the answer, L2 checks whether it is true" (A1_FAQ p.4). The human L2 layer earned its cost — across twelve fields, 7 agreed / 2 disagreed / 3 unclear, and **L2 found two defects the machine checks had passed**.

## 8 · Risks, limitations, responsible use *(ILO 2, 3, 4)*

**Decision: every risk carries its mitigation on the same line.** "Every risk needs its mitigation on the same line. A risk list without fixes is a description, not a plan." (Watchouts p.3)

| Risk | Mitigation, as built |
|---|---|
| **Hallucinated experience** | No-fabrication prompt rule; unsupported skills stripped; `FabricationGuard` (README §6) |
| **Silent failure** (PS §8 Risk 2) | Chunk IDs logged; confidence from similarity *and* self-report; abstain if **either** is low (README §5) |
| **Form misalignment** | Simulated form labelled `Prototype - not for live sites`, which "never submits anywhere" (README §1.4) |
| **Data leakage** | In-memory; hashes logged, never raw text (README §9) |
| **Injection via the pasted JD** | Hijack patterns redacted; the pasted text is fenced as data, never as instructions (README §9) |

**The silent failure, named.** "A prompt asks. A permission enforces." (Class6_Close p.6): the server has **no write or submit route**.

**Frameworks: two drifts reported, not blended** (report_en.md §8).

**Intended use:** a resume *reference and practice* tool, run locally, suggestions confirmed by a human. **Non-use:** real submissions, fictitious history, auto-submission, real candidate data (PS §8).

**AI disclosure.** "Did it write or rewrite something that ended up in your submission, or did it change a decision you made? If yes, it counts" (A1_FAQ p.5).

| FAQ category (A1_FAQ p.5) | Used? | Helped | Misled |
|---|---|---|---|
| Chat assistants | **Yes (agentic)** | Iterated the report across eight versions and 43 patch passes, from 2,876 to 1,375 non-table words; checked 26 course quotations against deck and page | Read “Hello Folks,.txt” as a filename and reported it missing — the real file is `study slides/final request.txt`; and declared the form-matrix `report.md` “final” though `run_form_matrix.py` regenerates it |
| Coding assistants in the editor | **Yes (agentic)** | Built the form-matrix driver (`run_form_matrix.py`, 19 runs, 205 checks); added the `/extract_resume` route and the PDF.js worker; wrote the `_verify_v*_quotes.py` scripts | Generated a `sender.tab` guard that silently cut the side-panel-to-backend channel; reported a UTF-8 mojibake in `report.md` that was a reader-side decode artifact, not a file defect |
| Search that answers rather than links | **No** | — | — |
| Writing and translation | **No** | — | — |
| Workplace assistants | **No** | — | — |
| Model calls inside the assignment | **No** — subject, not assistance | — | — |

## 9 · Smallest first version *(ILO 2)*

**Decision: build the end-to-end path first, and describe the slice, not a date.** "A date is not a version" (Watchouts p.3). The first slice was one input → one model call → one output, with the pass/fail sentence written before the build: at least **16 of 20** cases with **zero fabricated skills** (PS §9). The agent was refused as a **commercial judgement** — a loop multiplies cost without changing the answer — and a browser assistant was added without touching the control flow: **scope decision, not scope creep**.

**Next:** build the router (ceiling one case above B; README §13), and separate the corpus change from the embedder change so the gain is attributed (report_en.md §10.9).

## 10 · Results

One run, three conditions, **20 cases each, 60 records, 0 errors** (README §1.1). Counts first — one miss is five points:

| Condition | Passed | Zero fabrication | Prefill all-match | Abstained |
|---|---|---|---|---|
| A — rule-based TF-IDF | **12/20** | 20/20 | 13/20 | 3/20 |
| B — prompt-only LLM | **17/20** | 20/20 | 17/20 | 0/20 |
| C — with retrieval (RAG) | **16/20** | 20/20 | 17/20 | 1/20 |

Against a bar of 16/20: **B and C clear it, A does not** (README §1.1). Every ratio divides by the same **20 fixed cases** — read "17/20" by first asking what the denominator was (Class1/C1 p.3). **The headline is B 17 > C 16: the retrieval rung did not pay.**

**The pre-committed kill condition fired:** the top rung gained nothing and cost more, agreed "before the pilot starts" (Class5/C2 p.18). **One prompt contract moved the number** to **17/20 in both conditions** (B +2, C +3), and **a second identical run reproduced all three counts** (README §1.1).

## 11 · Cost

The business question is not the token rate but the cost of one **successful** task (report_en.md §11).

| | A | B | C |
|---|---|---|---|
| Model calls | 0 | 60 | 60 |
| Cost, 20 cases | $0.0000 | $0.0137 | $0.0154 |
| Cost per case | $0.0000 | $0.0007 | $0.0008 |
| Median latency per case | 16 ms | 8,289 ms | 8,375 ms |
| **Cost per successful task** | **$0.0000** | **$0.0008** | **$0.0010** |

**C spends more per success than B and succeeds less often.** The model path is roughly **500× slower** than the rules path — fine for one form typed at a desk, awkward if batched.

**The economic case:** condition B costs $0.0008 per successful task — cheaper than the human minutes it saves, and cheaper than condition C, which buys no accuracy for its 25% higher per-success cost.

## 12 · What this does not claim

**Decision: end on the limitations, not the result.**

The zero-fabrication figure in the form-matrix path is **structurally zero** (report.md §6). The time saving is **unmeasured** (feedback line 10). The router is **deliberately unbuilt** (README §13); one measured gain is **unattributed** (report_en.md §10.9); the wider 40-case evaluation was never run (README §1.2); and the side panel container needs a human click.

**The commercial case:** a trust-building assistant that declines rather than invents, priced per successful task, and cheaper than the problem it solves. "Carry the method. The facts have a shelf life; the questions do not." (Class6_Close p.6)
