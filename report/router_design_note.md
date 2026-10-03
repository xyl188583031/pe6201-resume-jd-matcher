# Router design note — should the field-level rule/model router be built?

**Status: document only. Nothing here is built, run or measured.** No delivered
number depends on this note. It exists because §10.1's finding (3) and §11's
lever 2 both point at a router, and an argument that appears twice in the report
deserves the arithmetic rather than the assertion.

This note is referenced from `report_en.md` §10.9 and §11.

---

## 1. What the "router" is, and what it is not

Here a router means **a per-field dispatcher**: for each form field the system
picks exactly one producer —

- the **rule path** (condition A: TF-IDF cosine similarity plus exact keyword
  overlap), which costs nothing, or
- the **model path** (conditions B and C), which costs $0.0007–$0.0008 per case.

It is *not* a model router in the gateway sense — that kind of router chooses
between two models on price or latency. This one chooses between a rule and a
model, so nothing off the shelf does it and the axis of the decision is
different. §5 of the main report already commits to "climbing the ladder only as
far as needed"; this is the same question asked per field instead of per system.

The routing key already exists: `server/field_map.classify` assigns every control
a category (`personal`, `education`, `experience_fact`, `skills`, …) before any
producer runs. The router is the *rule over that key*, not new classification.

---

## 2. The evidence that motivates it: the two producers fail on disjoint fields

Taken from §10.1, §10.2 and §10.3 of the main report, all on the same 20 cases:

| Field | A (rule) | B / C (model) |
|---|---:|---:|
| `full_name` | 20/20 | 20/20 |
| `email` | 20/20 | 20/20 |
| `education_school` | **14/20** | **20/20** |
| `top_skills` | **18/20** | **17/20** |

Two of the four scored fields are saturated and carry no information; the other
two split cleanly, and **each producer is strictly better on a different one**.

The same split appears at case level. A's eight failures (§10.2):

| Cause | Cases | Count |
|---|---|---:|
| `education_school` miss | AIML-v02, SE-v02, DA-v02, PM-v02 (the four `sparse_formal`), AIML-v05, SE-v05 (two `medium_plain`) | 6 |
| `top_skills` miss | AIML-v04, SE-v05 | 2 |
| declined the case | PM-v05 | 1 |

(SE-v05 carries both a school miss and a skills miss, so the nine cause-hits sit
on eight distinct cases.) B's three failures are **all** `top_skills`, and none
is a decline: AIML-v04, SE-v05, PM-v05. C adds one declined case, SE-v04.

So A's weakness is a *regex* weakness on institution names, and the model's
weakness is a *relevance-judgement* weakness on skills. They overlap on exactly
one case, SE-v05.

---

## 3. What a router could reach — as a derived ceiling, not a measurement

The following is arithmetic on the per-field counts in §2. **It is not a run and
it is not a result.** One case is 5 points at n=20, so read every gap here as "a
fraction of one case".

**Route `top_skills` to A, everything else as before.** B fails only on
`top_skills` (three cases), and A's `top_skills` misses only two of those three
(AIML-v04, SE-v05 — PM-v05's skills are correct for A). Substituting A's skills
therefore converts PM-v05 into a pass: **3 failures → 2 → 18/20**, against B's
17/20. This direction has no ambiguity, because B never declines.

**Route `education_school` to the model.** A's six school failures are all fixed
by a producer that scores 20/20 on that field. What remains is AIML-v04 and
SE-v05 (its own `top_skills` misses, untouched) plus PM-v05 — and PM-v05 is the
open question: A failed it by **declining the whole case**, not by getting a
field wrong. So the ceiling is **18/20 if the router does not inherit A's
case-level decline**, and **17/20 if it does**. That single cell is the difference
between "beats both conditions" and "ties the best one".

**Take both directions together** and the ceiling is **18/20**, failing only
AIML-v04 and SE-v05 — the two cases where the chosen producers are each at their
own worst. Nothing in this note claims 18/20 was achieved; it is the number the
per-field counts imply, and it is one case above the best delivered condition.

**This is the correction §11 needs.** §11 says a router "would beat either
condition alone on this set". Under the optimistic reading above that is right
(18 against 17). Under the conservative reading — the router keeps A's decline
behaviour, which is the only behaviour A has today — it **ties** B at 17/20
rather than beating it. The honest form of the claim is: *a router is worth at
most one case over the best single condition, and the sign of that one case
depends on who owns the decline decision.*

---

## 4. The build side, costed honestly

Building it means three things, and the third is the expensive one:

1. **A routing rule.** Cheap — a table from `field_map` category to producer.
   This is the part the word "router" makes sound like the whole job.
2. **Two producers running per case.** A currently produces a full bundle and the
   model produces a full bundle; field-level routing means running both and
   merging by category, or issuing a per-field instruction inside one call.
3. **A merge and a decline decision on the write path.** This is genuinely new
   code on the path that writes into a form. The current design routes field
   values through `server/services.py` with the abstention decision made once per
   case by a deterministic threshold (§7 of the main report). A per-field merge
   has to answer: if A banks a value and the model declines it, who wins? The
   project's own rule from §4 — *guarantees in code, judgement in the prompt* —
   says a merge must be a rule, and writing that rule correctly is the real work
   here, not the dispatch table.

**There is no free lunch on cost.** Per *field*, A is free; but A is free because
it is a computation, and the router's saving would only materialise on cases the
router does **not** send to the model at all. That is a case-level saving, and it
has not been measured. What this note can say is narrower: routing `top_skills`
to A would leave a case-level result that no longer needs the model's skills
judgement — but the model is still called for the match explanation, so the
sixty model calls in §11 do not disappear.

---

## 5. The buy side: nothing to buy on this axis

Searched against what the system needs, not against the word "router":

- **LLM gateways with model fallback** (the common meaning of "router") choose
  between *models* on price, latency or availability. They solve vendor
  reliability. They cannot express "send `education_school` to a regex".
- **Hosted classification/routing services** would put a résumé and a JD on a
  third party's infrastructure, which contradicts the data-control position the
  main report stakes out as one of the tool's three reasons to exist (§2, §5).
- **A workflow/branching product** (the low-code route already attempted in §5)
  could express the branch, but it re-imports the exact dependency that attempt
  failed on: the branch would sit outside the repository, owned by someone else.

So the buy side is empty and the comparison is not build-versus-buy. It is
build-versus-**leave-it-alone**, which is a different and cheaper question.

---

## 6. The decision, and what would change it

**Decision: do not build it in this round.** Three reasons, in order:

1. **The prize is one case on twenty, and the sign is not settled** (§3). This
   report already refuses to read one-case differences as signal — §12.1 calls a
   1-or-2-out-of-20 cell "a flag, not a measurement", and §10.1 declines to read
   C's one-case deficit as a verdict. Applying that standard here means the
   router's advertised gain is *inside* the noise the report has already declared
   unreadable.
2. **It puts new code on the write path for that one case.** §4's rule is that
   guarantees live in code and judgement lives in the prompt; a merge is
   judgement, and the safest merge (the model's decline always wins) is exactly
   the version that yields the conservative 17/20 reading.
3. **The ablation that would justify it has not been run.** A per-field producer
   comparison on a set where *both* weak fields are exercised per case is the
   experiment; n=20 with one case at 5 points is not that set.

**What would change the decision.** Either of these, and only these:

- a set where the two weak fields both matter on the same cases, large enough
  that one case is not 5 points; or
- a measured case-level saving — evidence that routing a field to the rule path
  removes model calls rather than merely changing which producer answers.

Until one of those exists, the router stays a design note.

---

## 7. What this note does not claim

- **No router was built, run or measured.** The 18/20 in §3 is arithmetic on
  §10.1–§10.3's own per-field counts, and it is labelled a ceiling throughout.
- **No cost saving is claimed.** §11's token table is unchanged by this note.
- **No claim about a different corpus, embedder or case set.** Every figure here
  is specific to the delivered run's 20 cases.
- **No claim that the two producers are complementary in general.** They are
  disjoint *on this set and on these two fields*. A larger set could show the
  model beating A on `education_school`'s long tail, or A beating the model on
  skills that are not in its pool — neither is tested here.
