# Form matrix - browser assistant under field and profile diversity

Driver: `scripts/run_form_matrix.py`. Runs: **19**. Controls seen: **561**.
Condition: **C** (retrieval + model). Server mode: **offline_stub** for every run.

Scope, stated first: this matrix drives the assistant's own HTTP contract
(`/scan` then `/generate`) with the content script's DOM extraction mirrored in
Python. It is not a browser run. Answer quality is not measurable here, because
the offline stub is a literal extractor, not a model.

## 1. Headline (counts)

**Mode: offline_stub - quality claims (fabrication, abstention quality, answer quality) do not apply to this matrix. See section 6.**

Total controls: **561**. Three groups are not candidates for a value at all: `not_fillable` 78 + `already_filled` 2 + `sensitive_skipped` 42 = 122. **Controls that could be filled: 439** - and the assistant offered **263/439** of them.

**Hard rule: sensitive 42/42 correctly withheld, with no value echoed.**

**Abstention triggered only on the cross-domain profile, only on posting-tailored fields (skills / experience / project, i.e. `services.TAILORED_CATEGORIES`):** 9 field(s) across 3 run(s), categories ['experience', 'project', 'skills']. Zero abstentions on personal or education facts - the documented design of `services._evidence_for_field`, and checked against the records rather than asserted in prose.

Decision distribution over every control in every run. Counts are the headline;
percentages are supplementary. All six states are kept and none is merged. The only
numbers that moved from round 1 are the ones the change log in section 8 records:
two controls, four counts.

| decision | fields | share | runs containing at least one |
|---|---:|---:|---:|
| `offered` | 263/561 | 46.9% | 19/19 |
| `abstained` | 9/561 | 1.6% | 3/19 |
| `missing` | 167/561 | 29.8% | 19/19 |
| `sensitive_skipped` | 42/561 | 7.5% | 19/19 |
| `not_fillable` | 78/561 | 13.9% | 19/19 |
| `already_filled` | 2/561 | 0.4% | 2/19 |

Arithmetic note, worth stating because it recurs whenever this table is checked against the API's own counts: the six buckets are *this script's* derivation, which classifies each control by precedence. `schemas.GenerateCounts` also counts `already_filled` orthogonally, so its own `already_filled` is larger - 11 run(s) hold a control that is both sensitive and already filled, and the server counts it in both buckets. The per-run reconciliation is asserted in the machine checks. No number above is the server's raw total, and none is meant to be.

**Fabricated claims: 0.** Structurally trivial in offline mode - the stub is a literal extractor and cannot invent, so this zero is about wiring, not about a real model. See sections 6 and 7.

| hard constraint | status |
|---|---|
| H2 no submission | PASS - 0 POST in the access log, 0 values offered for submit-shaped controls |
| H3 no persisted plaintext | PASS - 3 file(s) scanned, 0 hit(s); chrome.storage.local out of reach of a non-browser check |
| H5 no document number | PASS - 42 identity control(s) across the matrix, all sensitive_skipped with no value; canary absent from every response |
| H6 missing means null | PASS - every missing/abstained/sensitive field has suggested_value = null |

Machine checks: 182 L1 check(s) passed before the report.

## 2. Which dimension moves which decision

### 2.1 Form shape (L-A: 6 forms x full_profile x jd_named, everything else held)

| form | dimension under test | controls | offered | abstained | missing | sensitive | not_fillable | already_filled |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| `form_01_baseline` | baseline (reference shape) | 29 | 17 | 0 | 6 | 2 | 4 | 0 |
| `form_02_naming` | field naming style + label source | 30 | 17 | 0 | 6 | 3 | 4 | 0 |
| `form_03_help_text` | help text in <legend> + legend-only field names | 30 | 16 | 0 | 8 | 2 | 4 | 0 |
| `form_04_maxlength` | maxlength tiers 50 / 300 / 1000 | 29 | 17 | 0 | 6 | 2 | 4 | 0 |
| `form_05_traps` | trap controls + page-side pre-fill | 30 | 16 | 0 | 6 | 2 | 5 | 1 |
| `form_06_bilingual` | bilingual labels + Chinese-only labels + contenteditable | 30 | 17 | 0 | 7 | 2 | 4 | 0 |

Reading of 2.1: **form markup has no vote in abstention; it only has a vote in field identification.** `abstained` is 0 in every form variant, and no markup suppresses a tailored answer. Every column that does move moves for a named reason: `missing` where a label stopped being recognisable, `offered` where a control is now refused rather than answered wrongly (section 5 #1), `not_fillable` where the page had locked a control (section 5 #2), `sensitive_skipped` where the form simply carries one more identity control, and `already_filled` where the page pre-filled one. The full movement list is below.

Movements against the `form_01_baseline` column, computed from the table above: `form_02_naming` sensitive_skipped +1, `form_03_help_text` offered -1, `form_03_help_text` missing +2, `form_05_traps` offered -1, `form_05_traps` not_fillable +1, `form_05_traps` already_filled +1, `form_06_bilingual` missing +1. Three different things move a cell, and this row is what separates them: a form-shape difference that the dimension under test is supposed to create (the extra sensitive control on `form_02_naming`, the Chinese-only label on `form_06_bilingual`), a control this round now refuses rather than answers wrongly (sections 5 #1 and #2), and the page-side pre-fill that exists to test edit-wins.

### 2.2 Profile and posting (L-B and L-C)

| run | resume | posting | offered | abstained | missing | sensitive | not_fillable | already_filled | retrieval active |
|---|---|---|---:|---:|---:|---:|---:|---:|---|
| `fm-L-B-form_01_baseline-full_profile-jd_named` | `full_profile` | `jd_named` | 17 | 0 | 6 | 2 | 4 | 0 | yes |
| `fm-L-B-form_01_baseline-sparse_profile-jd_named` | `sparse_profile` | `jd_named` | 9 | 0 | 14 | 2 | 4 | 0 | yes |
| `fm-L-B-form_01_baseline-cross_domain_profile-jd_named` | `cross_domain_profile` | `jd_named` | 15 | 1 | 7 | 2 | 4 | 0 | yes |
| `fm-L-B-form_01_baseline-long_prose_profile-jd_named` | `long_prose_profile` | `jd_named` | 17 | 0 | 6 | 2 | 4 | 0 | yes |
| `fm-L-B-form_01_baseline-minimal_profile-jd_named` | `minimal_profile` | `jd_named` | 3 | 0 | 20 | 2 | 4 | 0 | yes |
| `fm-L-C-form_01_baseline-cross_domain_profile-jd_cross_domain` | `cross_domain_profile` | `jd_cross_domain` | 9 | 7 | 7 | 2 | 4 | 0 | yes |
| `fm-L-C-form_06_bilingual-cross_domain_profile-jd_named` | `cross_domain_profile` | `jd_named` | 15 | 1 | 8 | 2 | 4 | 0 | yes |
| `fm-L-C-form_05_traps-sparse_profile-jd_implied` | `sparse_profile` | `jd_implied` | 8 | 0 | 14 | 2 | 5 | 1 | yes |
| `fm-L-C-form_04_maxlength-long_prose_profile-jd_named` | `long_prose_profile` | `jd_named` | 16 | 0 | 7 | 2 | 4 | 0 | yes |
| `fm-L-C-form_03_help_text-minimal_profile-jd_implied` | `minimal_profile` | `jd_implied` | 3 | 0 | 21 | 2 | 4 | 0 | yes |

Reading of 2.2: abstentions appear in 3 run(s), on profile(s) ['cross_domain_profile'] and posting(s) ['jd_cross_domain', 'jd_named'].
And in each case the withheld fields are the ones whose answer has to be tailored
to the posting (skills, experience, project). The mechanism is visible in the
records: `components_present` carries the retrieved score, and the reason string
names the component that fell under the threshold. Nothing abstains on a
personal or education fact, which is the documented design of
`services._evidence_for_field`.

### 2.3 `missing` tracks profile completeness

Read from the L-B runs only: same form, same posting, the resume is the one variable.

| profile | `missing` count |
|---|---:|
| `full_profile` | 6 |
| `sparse_profile` | 14 |
| `minimal_profile` | 20 |

The three are strictly increasing - 6 < 14 < 20 - which is what makes the column readable at all: `missing` is tracking how much the candidate supplied, not noise. This matters for section 2.1, where `missing` is the only column a form shape is allowed to move. The ordering is asserted as a machine check, so it cannot quietly stop holding.

## 3. The four hard constraints, per form

Each cell is the number of runs of that form in which the constraint held, over the
number of runs of that form in the matrix.

| form | H2 no submit | H3 no plaintext | H5 no document number | H6 missing means null |
|---|---|---|---|---|
| `form_01_baseline` | 7/7 | 7/7 | 7/7 | 7/7 |
| `form_02_naming` | 4/4 | 4/4 | 4/4 | 4/4 |
| `form_03_help_text` | 2/2 | 2/2 | 2/2 | 2/2 |
| `form_04_maxlength` | 2/2 | 2/2 | 2/2 | 2/2 |
| `form_05_traps` | 2/2 | 2/2 | 2/2 | 2/2 |
| `form_06_bilingual` | 2/2 | 2/2 | 2/2 | 2/2 |

H2 evidence, in full: no value is offered for a control whose type is submit,
button, reset, image, file, password or hidden (`not_fillable` in every run); the
OpenAPI surface exposes exactly the five documented endpoints and none of them
writes or submits; and the static server's access log over the whole matrix contains
**0 POST requests** against 19 GET requests.
Residual gap, stated: *clicking* the submit control in a real browser is not exercised
here. `extension/scripts/browser_check.mjs` covers that on the demo page, and
`scripts/manual_panel_check.md` covers it per form by hand.

H5 evidence, in full: every identity-document control is reported
`sensitive_skipped` with an empty `value_hash`; the canary value planted on the pages
never appears in any response body in any run.

**H5 boundary definition:** `server/README.md` section 4.3, *Definition of "transmitted" in H5* - link `server/README.md#43-definition-of-transmitted-in-h5`.
A value counts as **transmitted** when it leaves this machine, reaches a model or a
third party, or is written to durable storage. It does **not** count as transmitted
when it stays in memory on this machine and is dropped before any of those happens.

Measured behaviour, restated against that definition rather than around it: the content
script's never-read list covers `password` and `file` only, so a document number that is
already typed into a page **does** cross the loopback socket to the local server, where
it is dropped - it never reaches a model, is never echoed to the panel, is never used as
a value and is never written to disk. Residual risk, named: a process already running on
this machine could observe that loopback socket.

The stronger option - withholding the value at the page - was considered and not taken
this round. Doing it would require the content script to know the document-number
patterns, which is a second implementation of a policy `server/field_map.SENSITIVE_PATTERNS`
owns and the one thing `server/README.md` section 3 forbids. The clean version is a
two-phase scan (shape first, values only for the fields the server did not refuse), which
is a design change, so it is recorded as a question for a later round.

## 4. L2 - human judgement, completed

Twelve fields were selected by the script (`render_l2()`); the verdict and note
columns in `artifacts/form_matrix/l2_review.md` are now filled in.

Verdict distribution (counts, not percentages):

| table | agree | disagree | unclear |
|---|---:|---:|---:|
| question set 1 (offered, 6 rows) | 6 | 0 | 0 |
| question set 2 (refused, 6 rows) | 1 | 2 | 3 |
| **total** | **7** | **2** | **3** |

**The two `disagree` rows, listed individually.** Both point at the same root
cause and are handed to section 5 as one finding (7a).

| run_id | field_id | label | why it is a disagree |
|---|---|---|---|
| `fm-L-C-form_01_baseline-cross_domain_profile-jd_cross_domain` | `wf_571f50676d64` | Company name | The profile holds `internship[0].employer = "Harbour Retail Group"` and `source` was identified as `internship.internship_employer`. In the L-A cell the same field is `offered` (confidence 0.752, deterministic copy path); in L-C it is withheld because the cross-domain JD drops the retrieval similarity to 0.00 (combined confidence 0.32). Same field, same source, different path across cells. |
| `fm-L-C-form_01_baseline-cross_domain_profile-jd_cross_domain` | `wf_f551d6320a36` | Job title | The profile holds `internship[0].title = "Operations Intern"` and `source` was identified as `internship.internship_title`. Same L-A / L-C contrast as Company name. |

**The `agree` whose reason is wrong** is handed to section 5 as finding 7b:

| run_id | field_id | label | what was right and what was wrong |
|---|---|---|---|
| `fm-L-C-form_01_baseline-cross_domain_profile-jd_cross_domain` | `wf_f263ef9b690a` | GPA | Correct **outcome** (`cross_domain_profile` declares `"gpa"` in `intentionally_absent` and carries no gpa key), but the reason reported to the user is `retrieval similarity 0.00 < threshold 0.40` whereas the true cause is "the profile has no such field". `source = "none"` confirms the classifier never placed this control in the education category. |

**The three `unclear` rows** are the three L-A narrative fields (`Why do you want
this role?` / `Cover letter` / `Additional information`). They are `missing`
because the offline stub has no drafting path (`only the retrieval component
exists for this condition`). This is a mode limit, not a correctness judgement;
the same fields in a live run would be candidates for a model-drafted answer.

**Self-assessment of the sample.** Twelve fields across two runs. The six rows
selected from the `offered` side carry low information: they are all personal-fact
fields whose classification is trivial once the label is recognised, so they are
guaranteed to agree. The refused side carried the real findings. The current
sampling rule (`first three offered in field order`) therefore samples the least
informative rows on this form; the next round should broaden it to draw from
`abstained` / `missing` fields whose category is `skills`, `experience`, `project`
or `narrative`.

To reproduce the L2 review, run:

```
RJD_OFFLINE=1 python scripts/show_l2_values.py
```

H3 scan coverage, for the record: 3 artifact file(s) and 0 temp file(s) were scanned against 78 sentinel string(s); hits: 0. `chrome.storage.local` status: `not_scanned_outside_a_browser` - the store exists only inside an extension context, so it is covered by `scripts/manual_panel_check.md`, not by this script.

## 5. Known failures and attribution

Ordered by **severity**, not by discovery order. The rule, stated so it can be argued
with: *user-visible error* (`high`) > *classification gap* (`medium`) > *reporting gap*
(`low`) > *untested* (`low`). A `fixed in round 2` row is kept rather than deleted: it
was a real failure of round 1, and the fix is what the change log in section 8 records.

Eight findings: 1 high, 5 medium, 2 low; 2 fixed this round, 5 left open (each with the reason it is open), and 1 recorded as not testable in offline mode rather than as open or fixed.

Attribution vocabulary, fixed in advance and unchanged this round: `bug` = the system
produced a wrong result on its own terms; `generation wobble` = the same input gave a
different result; `edge` = a form or data shape outside what the current design claims
to cover. **`generation wobble` is not observable in offline mode (see M3)**, so no row
carries it: the L-D row states why instead.

| # | severity | status | what happened | attribution | evidence |
|---:|---|---|---|---|---|
| 1 | `high` | fixed in round 2 | form_03: the employer control is labelled `Name` inside an `Employer details` section, so the generic name fallback (`_FALLBACK_NAME`) classified it as the candidate's own name and the assistant offered the candidate's full name into the employer box (2 run(s) in round 1). **Round 2:** section text is context and may no longer name a field, so the control is refused (`missing`) rather than filled with the wrong fact. | `bug` | round-1 records: field `name_2`, label `Name`, decision `offered`, source `personal_info.full_name`; round-2 records: decision `missing`; regression `tests/test_form_matrix_regressions.py::test_legend_never_names_a_field`; source `server/field_map.classify` + `extension/src/content.ts:isSectionLevelText` |
| 2 | `medium` | fixed in round 2 | form_05: the `readonly` control was treated as fillable and offered a value - nothing in the skip table or the content script's fillable test knew about readonly (2 run(s), every one `offered` in round 1). **Round 2:** `readonly` is refused at the page (never read, never written) and in `field_map.SKIPPED_ATTRIBUTES`, so the control is `not_fillable` with no value. | `edge` | round-1 records: field `email_readonly`, decision `offered`; round-2 records: decision `not_fillable`, `value_hash` empty; regression `tests/test_form_matrix_regressions.py::test_readonly_control_is_not_fillable`; source `server/field_map.SKIPPED_ATTRIBUTES` + `extension/src/content.ts:isReadonlyControl` |
| 3 | `medium` | open - not fixed in this round; recorded as a design question | form_06: a label written only in Chinese is unclassifiable - `_FIELD_MAP` has no Chinese patterns except in the identity-document block - so '补充说明' is reported missing while its English twin would be answered | `edge` | round records, field `beizhu`, category `unknown`, decision `missing`. Adding Chinese patterns to `_FIELD_MAP` is a classifier decision for the pipeline, not for this matrix. |
| 4 | `medium` | open - not fixed in this round; recorded as a design question | form_04: a short character limit meets an unbreakable token and the assistant reports the field as unanswerable instead of shortening a URL - which it could do without inventing anything (seen on linkedin (limit 50)) | `edge` | round records, message kind `length_unanswerable`. Not fixed in this round; recorded as a design question - a URL-aware `fit_to_length` would change `server/services.fit_to_length`, which is the pipeline's decision, not this matrix's. |
| 7a | `medium` | open - design question | experience classification is unstable at the tailored / fact boundary: `services._evidence_for_field` classifies all of `experience` as tailored, so fact-shaped sub-fields (`Company name`, `Job title`) inherit the posting's retrieval score and are withheld on a cross-domain posting even when the profile plainly states them | `edge` | L2 question set 2 rows 5-6; `wf_571f50676d64` / `wf_f551d6320a36`; the L-A vs L-C contrast in the same fields (`offered` at 0.752 vs `abstained` at 0.32, same `source`) |
| 7b | `medium` | open - design question | `missing` reason is attributed to retrieval when the profile simply has no such fact: a control whose fact key is absent from the profile is reported `missing` with the reason `retrieval similarity 0.00 < threshold 0.40` and `source = "none"`, which sends the user to fix the posting instead of the profile | `edge` | L2 question set 2 row 4; `wf_f263ef9b690a`; `cross_domain_profile.json` declares `"gpa"` in `intentionally_absent` |
| 5 | `low` | open - not fixed in this round; recorded as a design question | form_05: a `<button type="submit">` is invisible to the scanner - the selector matches `input` only - so the panel cannot report it as a refused control. It is also why it cannot be clicked by the assistant, so the effect is a reporting gap, not a safety one | `edge` | form_05 field inventory vs the scan payload: `confirm_application` absent |
| 6 | `low` | not testable in offline mode | L-D: **not testable in offline mode.** The same cell was run 3 time(s) and produced 1 distinct outcome(s) - but the offline stub is a literal extractor: it has no sampler, so any repetition must agree. This is a property of the stub, not evidence that a live model would be stable. | `edge` | run records for L-D compared on (field_id, decision, value_hash). Stability requires `mode=live_api`; it is not claimed by this matrix - see section 6. |

L-D is structurally deterministic in offline mode; see §6.

## 6. Limitations

Six required limitations, none omitted:

1. **Not a browser run.** The content script's extraction is mirrored in Python. The
   real content script is verified separately by `extension/scripts/browser_check.mjs`.
2. **Offline stub only.** `RJD_OFFLINE=1` for every run, so the drafting is a literal
   extractor. `fabricated_claims == 0` therefore says the guards and the wiring hold on
   this data - it is **not** evidence that a live model would not fabricate.
3. **Stability (generation wobble) is not testable in offline mode.** The stub has no
   sampler, so any repetition must agree; the L-D probe still runs, and its agreement is
   a property of the stub rather than a measurement of the product. Stability requires
   `mode: live_api`; it is not claimed by this matrix.
4. **`chrome.storage.local` was not inspected.** It exists only inside an extension
   context, and the matrix runs outside the browser, so this surface is covered by
   `scripts/manual_panel_check.md`, not by this script.
5. **Corpus limit still standing.** The similarity scale is the one already documented
   for the same 54-chunk knowledge base (floor 0.3663, ceiling 0.5633). The knowledge
   base was not rebuilt and `scripts/calibrate_similarity.py` was not run, so no
   recalibration is being claimed. Change the corpus and these numbers are void.
6. **Timing metrics remain disabled** (H8). No duration appears anywhere in this
   report, and none was measured.

Also outside those six:

- **Dimensions not covered.** No unsaved-draft flow, no multi-step wizard, no same-name
  repeated controls across sections, no dynamically inserted fields, no iframe or shadow
  DOM, no `<button>`-based form controls beyond the one absence recorded in section 5,
  no non-Latin label tested beyond Chinese, and no right-to-left text.
- **`disabled` controls were not measured.** A disabled input is still scanned and still
  treated as fillable - the same family of mistake as `readonly`, which this round fixed.
  It is recorded as a design question rather than silently fixed, because the matrix
  never planted one.
- **The page-side halves of this round's two fixes are unverified in a browser.** The
  server-side refusals are pinned by `tests/test_form_matrix_regressions.py`; the content
  script's own `readonly` refusal and its section-context reporting are covered only by
  `scripts/manual_panel_check.md`.
- **Side panel rendering is covered by the manual checklist, not by this script.**
  `scripts/manual_panel_check.md` is the procedure; `chrome.sidePanel.open()` refuses
  a synthetic gesture, which is why it cannot be automated.

Source fingerprint (H7):

| file | sha256 |
|---|---|
| `config.yaml` | `a787ab8f60b875dc2c6c38773575830b6a9aface149025fa31ae56ac9219ac4f` |
| `src/pipeline/confidence.py` | `0e06e38d720462ce7c8aec52308458807c40d65a92488d05fc8e482cf6d04629` |
| `src/rules/fields.py` | `aab029a1e633dce5a76304c0a8ad93afb8ea7a8a09daa27bdcc88801daf9024d` |
| `src/taxonomy.py` | `9a52510e34cb29a23e9a72a303d47f46eadf6c46830495b195f7302a24bf77c3` |
| `src/retrieval/store.py` | `ecf4c6b6b2b451c28b605758089bfaf0e66552da529db95602a56160f273dba1` |
| `src/llm/extractor.py` | `73bfaa0e4faebe0037b79ea3d84eab3914d5447f94d75c349c861d7220d382ed` |
| `src/llm/offline.py` | `0278f7efe1bfc500de8b1ccef483b11d4b9b746e8fe9cb3f62fc3739a2cb4bd7` |
| `src/sanitize.py` | `8e97d716cb32be54232cd7da2701895b0c71ff1ee24a1b9b7dffcc446f3b3bd9` |
| `server/field_map.py` | `ed0d6ecde715739a4f71764a4d191938bd6da1171a9eed0142b65cd7dce571a5` |
| `server/services.py` | `ea64fed1b89e8709735641135aee5cfee130c9e32ba5be76f0488b633dfd9d6a` |
| `server/schemas.py` | `c8d83a86a03c07f52455fcf160c8f58016d90d8b4e3c86763c51dc2907268511` |
| `extension/src/content.ts` | `5f4eda65e7f9936133d31335262a8d50243c2b4cf3d9097720afe63925355ac0` |

Full digests, not prefixes: this table exists to be recomputed, and a prefix cannot be
checked. The same values are in `artifacts/form_matrix/source_fingerprint.json`, and
both come from one `source_fingerprint()` call, so neither can drift from the files it
names.

Abstention threshold read back: **0.4**, weights
retrieval 0.6 / llm_self 0.4,
abstain-on-either **True**. None of these were changed.

## 7. Live spot-check

Why exactly two runs, and these two. The offline matrix has three blind spots it cannot
close by itself: (a) the classification trap, the section-naming case in section 5 #1;
(b) the sparsest profile, where `missing` is densest and a model has the most room to
invent; and (c) the cross-domain posting, the only configuration that produces
abstentions. Two cells cover all three, which makes them the smallest set worth paying
for:

- `form_03_help_text` x `full_profile` x `jd_named`
- `form_05_traps` x `sparse_profile` x `jd_implied`

The rest of the matrix is deliberately *not* re-run live. `fabricated_claims == 0` in
offline mode is structurally zero - the stub is a literal extractor, so it cannot invent
- and only a real model can turn that into a zero that was earned. When these two cells
are run, their results go to `artifacts/form_matrix/live_spot_check.md` and are never
merged into the tables above: they are a different mode, a different model and a
different question.

Live spot-check deferred by scope, not by cost: the two cells are cheap (of the order of $0.001 each against `openai/gpt-4o-mini`), but a live run would open a second mode - a real model, a different question - that this matrix is not structured to carry. Left to the next round; the offline zero-fabrication figure stays labelled structurally trivial until then.

## 8. Change log - what round 2 moved

Two defects were fixed, so counts moved. Nothing was adjusted to make a number read
better: the *before* column is what the round-1 run recorded, the *after* column is
recomputed from this run, and every after value is asserted against the value the fix
predicts. A metric that is not in this table did not move.

| metric | before (round 1) | after (this run) | direction | why it moved |
|---|---:|---:|---|---|
| `form_03_help_text` `offered` | `17` | `16` | down | the employer control is refused instead of answered with the candidate's name (section 5 #1) |
| `form_03_help_text` `missing` | `7` | `8` | up | the same control: `missing` is the only bucket an `offered` loss can land in |
| `form_05_traps` `offered` | `17` | `16` | down | the readonly control is refused (section 5 #2) |
| `form_05_traps` `not_fillable` | `4` | `5` | up | the same control, now counted as one we never touch |
| `name_2` decision | `offered` | `missing` | changed | was `offered` as `personal_info.full_name`; now `missing` |
| `email_readonly` decision | `offered` | `not_fillable` | changed | was `offered`; now `not_fillable` |
| whole matrix `offered` | `267` | `263` | down | two controls, two runs each: `name_2` and `email_readonly` |
| whole matrix `missing` | `165` | `167` | up | `name_2` appears in 2 runs |
| whole matrix `not_fillable` | `76` | `78` | up | `email_readonly` appears in 2 runs |

One prediction could not hold, and it is arithmetic rather than opinion. The brief
expected `form_03 offered` to fall 17 -> 16 *and* `form_03 missing` to fall 7 -> 6 at the
same time. The field total for that form is fixed at 30, `abstained` and
`sensitive_skipped` cannot move in offline mode, and `not_fillable` is unchanged on
form_03 - so a control leaving `offered` has exactly one bucket left to land in, and it
is `missing`. The recorded outcome is `offered` 17 -> 16 with `missing` 7 -> 8.

`abstained` did not move (9 fields, all on the cross-domain profile) and
`sensitive_skipped` did not move (42 fields, every one withheld with no value).

Two things changed in the *report* itself without a count changing. Both repair round 1
rather than edit it quietly:

- Round 1's section 2.1 called `sensitive_skipped` constant across form variants. It is
  not: `form_02_naming` carries 3 identity controls where every other form carries 2, so
  the column moves by +1 there. The reading now names that cause instead of denying it,
  and the movement list under the table enumerates it.
- The fingerprint table prints the full digest. A 16-character prefix cannot be
  recomputed against the file it names, and a table that cannot be checked is decoration.