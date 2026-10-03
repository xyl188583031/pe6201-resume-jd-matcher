# L2 - human judgement sheet

Not graded by the script. The verdict and note columns are filled in by hand,
below. Every verdict is one of `agree` / `disagree` / `unclear`.

**This file is hand-filled once and is not overwritten.** A later run writes
`l2_review.generated.md` instead, so the verdicts below survive: they are
round-2 evidence and editing them would destroy it. Round 3 changed two things
only - the `status` line on each of the two findings, and the one note below
whose mechanism turned out to be wrong. Both changes are marked where they are.

Selection rule: the first run of L-A and the first run of L-C in run order, then the
first three fields of each whose decision is `offered`, taken in field order. Fields
are chosen this way so the reviewer spends their attention on values that were actually
offered, which is where a wrong answer would reach a user.

Values are **not** in this file: the run log stores a hash and a length only (H3).
To judge a row, re-run the same cell and read the panel, or read the live page.
Reproduce with:

```
RJD_OFFLINE=1 python scripts/show_l2_values.py
```
## Question set 1 - fields the system offered

Question for every row: *does this value really come from the candidate's profile,
and is it in the correct field? Should it have been withheld instead?*

| run_id | field_id | label | system_decision | system_reason | question | verdict | note |
|---|---|---|---|---|---|---|---|
| `fm-L-A-form_01_baseline-full_profile-jd_named` | `wf_409c03990f25` | Full name | `offered` | (no reason string on this row) | Value from profile? Correct field? | `agree` | Value = `full_profile.personal_info.full_name` (`"Zhang Wei"`); field semantics match. |
| `fm-L-A-form_01_baseline-full_profile-jd_named` | `wf_36bfd748fcd2` | Email address | `offered` | (no reason string on this row) | Value from profile? Correct field? | `agree` | Value = `full_profile.personal_info.email` (`"zhang.wei@example.edu"`); field semantics match. |
| `fm-L-A-form_01_baseline-full_profile-jd_named` | `wf_459eca7fb38d` | Phone | `offered` | (no reason string on this row) | Value from profile? Correct field? | `agree` | Value = `full_profile.personal_info.phone` (`"+65 9123 4567"`); field semantics match. |
| `fm-L-C-form_01_baseline-cross_domain_profile-jd_cross_domain` | `wf_409c03990f25` | Full name | `offered` | (no reason string on this row) | Value from profile? Correct field? | `agree` | Value = `cross_domain_profile.personal_info.full_name` (`"Nurul Hakim"`); field semantics match. |
| `fm-L-C-form_01_baseline-cross_domain_profile-jd_cross_domain` | `wf_36bfd748fcd2` | Email address | `offered` | (no reason string on this row) | Value from profile? Correct field? | `agree` | Value = `cross_domain_profile.personal_info.email` (`"nurul.hakim@example.com"`); field semantics match. |
| `fm-L-C-form_01_baseline-cross_domain_profile-jd_cross_domain` | `wf_459eca7fb38d` | Phone | `offered` | (no reason string on this row) | Value from profile? Correct field? | `agree` | Value = `cross_domain_profile.personal_info.phone` (`"+65 8788 1200"`); field semantics match. |

**Sub-total, question set 1: agree 6 / disagree 0 / unclear 0.**

Note on information content: all six rows are personal-fact fields that go through
`services._evidence_for_field`'s fact path (deterministic extraction confidence,
no retrieval, no model). They are structurally guaranteed to agree whenever the
classifier maps them correctly. The selection rule (first three `offered` in field
order) therefore samples the *least* informative rows on this form; the same rule
applied to a narrative- or experience-heavy form would sample differently. This is
recorded as a limitation of the current sampling rule, not as a defect.

## Question set 2 - fields the system refused

The inverse question: *was refusing right, or did the system withhold something the
profile plainly states?*

| run_id | field_id | label | system_decision | system_reason | question | verdict | note |
|---|---|---|---|---|---|---|---|
| `fm-L-A-form_01_baseline-full_profile-jd_named` | `wf_4ba3bef9d2b3` | Why do you want this role? | `missing` | only the retrieval component exists for this condition; confidence equals that component | Was refusing right? Is the answer in the profile? | `unclear` | Offline stub has no drafting path for narrative fields; the reason states a mode limit, not a correctness judgement. In a live run this field would be a candidate for a model-drafted answer. |
| `fm-L-A-form_01_baseline-full_profile-jd_named` | `wf_cf2dbc97045a` | Cover letter | `missing` | only the retrieval component exists for this condition; confidence equals that component | Was refusing right? Is the answer in the profile? | `unclear` | Same as above. |
| `fm-L-A-form_01_baseline-full_profile-jd_named` | `wf_628fecac04fd` | Additional information | `missing` | only the retrieval component exists for this condition; confidence equals that component | Was refusing right? Is the answer in the profile? | `unclear` | Same as above. |
| `fm-L-C-form_01_baseline-cross_domain_profile-jd_cross_domain` | `wf_f263ef9b690a` | GPA | `missing` | only the retrieval component exists for this condition; confidence equals that component | Was refusing right? Is the answer in the profile? | `agree` | Correct **outcome** (the cross_domain_profile declares `"gpa"` in `intentionally_absent` and its education block carries no gpa key), but the **reason is wrong**: the system reports `retrieval similarity 0.00 < threshold 0.40` whereas the true cause is "the profile has no such field". `source = "none"` shows the classifier matched no fact for this control. **Corrected in round 3:** reading that as "never classified as `education`" was wrong - the record gives `category = education` and `fact_key = gpa`, and the field is `missing` because the profile carries no GPA. The defect is reason attribution, not confidence. Fixed in round 3; the reason now names the absent fact. |
| `fm-L-C-form_01_baseline-cross_domain_profile-jd_cross_domain` | `wf_571f50676d64` | Company name | `abstained` | combined confidence 0.32 < threshold 0.40; retrieval similarity 0.00 < threshold 0.40 | Was refusing right? Is the answer in the profile? | `disagree` | The profile explicitly holds `internship[0].employer = "Harbour Retail Group"` and `source` was correctly identified as `internship.internship_employer`. In the **L-A cell** the same field is `offered` (Acme Corp, confidence 0.752, offline-stub verbatim-copy path). In **L-C** it is withheld because the cross-domain JD drops the retrieval similarity to 0.00 (combined confidence 0.32). Same field, same source, different path across cells -> the experience category is unstable at the tailored / fact boundary. **Fixed in round 3:** this cell now reports `offered`, and the whole run reads `offered` 13 / `abstained` 3. |
| `fm-L-C-form_01_baseline-cross_domain_profile-jd_cross_domain` | `wf_f551d6320a36` | Job title | `abstained` | combined confidence 0.32 < threshold 0.40; retrieval similarity 0.00 < threshold 0.40 | Was refusing right? Is the answer in the profile? | `disagree` | The profile explicitly holds `internship[0].title = "Operations Intern"` and `source` was correctly identified as `internship.internship_title`. Same L-A / L-C contrast as Company name (offered at 0.752 in L-A, withheld at 0.32 in L-C). Same root cause. **Fixed in round 3**, by the same split. |

**Sub-total, question set 2: agree 1 / disagree 2 / unclear 3.**

## Verdict distribution

Counts, not percentages.

| table | agree | disagree | unclear |
|---|---:|---:|---:|
| question set 1 (offered, 6 rows) | 6 | 0 | 0 |
| question set 2 (refused, 6 rows) | 1 | 2 | 3 |
| **total** | **7** | **2** | **3** |

## Findings derived from L2

Two findings are handed to `report.md` section 5. They are listed here so a
reader can see the verdict, the raw rows, and the reason side by side. Both were
written as `open - design question` at the end of round 2 and both were fixed in
round 3; the status line on each records that, and the round-3 rows of
`report.md` section 8 list every count that moved as a result.

**Finding 7a - experience classification is unstable at the tailored / fact boundary.**

- severity: `medium`
- status: `fixed in round 3` (was `open - design question` at the end of round 2)
- what: `services._evidence_for_field` classifies all of `experience` as tailored, so
  fact-shaped sub-fields (`Company name`, `Job title`) inherit the posting's
  retrieval score. On a cross-domain posting the retrieval score is 0.00 and these
  fields are withheld even though the profile plainly states them.
- evidence: question set 2 rows 5 and 6; `wf_571f50676d64` and `wf_f551d6320a36`;
  the L-A / L-C contrast in the same fields (`offered` at 0.752 vs `abstained` at
  0.32 with the same `source`).
- fix direction (recorded in round 2, **taken in round 3**): split
  `experience_employer` / `experience_title` / `experience_dates` and
  `project_name` into fact categories in `server/field_map.py`, so they use the
  deterministic extraction confidence rather than the retrieval score. The
  narrative halves (`internship_summary`, `project_summary`) stayed tailored,
  which is the point of a split rather than a relaxation: a summary genuinely is
  an answer to the posting, an employer's name is not. In the cell where this
  showed up, `offered` went 9 -> 13 and `abstained` 7 -> 3; the other eight runs
  did not move at all. Pinned by
  `tests/test_form_matrix_regressions.py::test_experience_facts_are_not_tailored`
  and carried as `report.md` section 5 row 4 (finding 7a).

**Finding 7b - `missing` reason is attributed to retrieval when the profile simply
has no such fact.**

- severity: `medium`
- status: `fixed in round 3` (was `open - design question` at the end of round 2)
- what: a control whose fact key is absent from the profile is reported `missing`
  with the reason "retrieval similarity 0.00 < threshold 0.40" and `source = "none"`,
  which sends the user to fix the posting instead of the profile.
- evidence: question set 2 row 4; `wf_f263ef9b690a`; `cross_domain_profile.json`
  declares `"gpa"` in `intentionally_absent`.
- fix direction (recorded in round 2, **taken in round 3**): when the profile
  carries no fact for a fact-shaped field, the reason names "no fact in the
  authorised profile" rather than the retrieval component. `_evidence_for_field`
  now returns no evidence at all in that case instead of handing the retrieval
  score to the formula. No count moved - the outcome was already `missing` - so
  this is a report repair, and `report.md` section 8 records it as one rather
  than inventing a number for it. Pinned by
  `tests/test_form_matrix_regressions.py::test_missing_reason_names_the_absent_fact`
  and carried as `report.md` section 5 row 5 (finding 7b).
- correction, recorded rather than quietly dropped: the row-4 note in question
  set 2 reads `source = "none"` as proof that "the classifier never placed this
  control in the education category". The round-3 record says otherwise - the
  category is `education` and the fact key is `gpa`; the field is `missing`
  because the profile carries no GPA. The finding was right about the symptom
  and wrong about the mechanism, and the fix is right for the corrected reason.

## Self-assessment of the sample

Twelve fields across two runs, six from the offered side and six from the refused
side. The offered side turned out to have low information content: all six are
personal-fact fields whose classification is trivial once the label is recognised.
The refused side carried the real findings: two `disagree` (7a) and one `agree`
whose reason is wrong (7b).

Next round, if L2 is repeated: broaden the sampling rule to draw from `abstained`
and `missing` fields whose category is `skills`, `experience`, `project` or
`narrative`, and drop the personal-fact fields from the offered side unless the
classifier's output is itself in question.