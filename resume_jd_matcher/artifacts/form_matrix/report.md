# Form matrix - browser assistant under field and profile diversity

Driver: `scripts/run_form_matrix.py`. Runs: **19**. Controls seen: **563**.
Condition: **C** (retrieval + model). Server mode: **offline_stub** for every run.

Scope, stated first: this matrix drives the assistant's own HTTP contract
(`/scan` then `/generate`) with the content script's DOM extraction mirrored in
Python. It is not a browser run. Answer quality is not measurable here, because
the offline stub is a literal extractor, not a model.

## 1. Headline (counts)

**Mode: offline_stub - quality claims (fabrication, abstention quality, answer quality) do not apply to this matrix. See section 6.**

Total controls: **563**. Three groups are not candidates for a value at all: `not_fillable` 80 + `already_filled` 2 + `sensitive_skipped` 42 = 124. **Controls that could be filled: 439** - and the assistant offered **267/439** of them.

**Hard rule: sensitive 42/42 correctly withheld, with no value echoed.**

**Abstention triggered only on the cross-domain profile, only on posting-tailored fields (skills / experience / project, i.e. `services.TAILORED_CATEGORIES`):** 5 field(s) across 3 run(s), categories ['experience', 'project', 'skills']. Zero abstentions on personal or education facts - the documented design of `services._evidence_for_field`, and checked against the records rather than asserted in prose. Round 3 shrank this set; section 2.2 names the fields that left and why.

Decision distribution over every control in every run. Counts are the headline;
percentages are supplementary. All six states are kept and none is merged. Three
defects fixed over two rounds moved these numbers - the employer misclassification
(section 5 row 1), the `readonly` control (row 2), the `disabled` control round 3
added (row 3) and the experience / project fact split (row 4). The change log in
section 8 lists every cell they touched.

| decision | fields | share | runs containing at least one |
|---|---:|---:|---:|
| `offered` | 267/563 | 47.4% | 19/19 |
| `abstained` | 5/563 | 0.9% | 3/19 |
| `missing` | 167/563 | 29.7% | 19/19 |
| `sensitive_skipped` | 42/563 | 7.5% | 19/19 |
| `not_fillable` | 80/563 | 14.2% | 19/19 |
| `already_filled` | 2/563 | 0.4% | 2/19 |

Arithmetic note, worth stating because it recurs whenever this table is checked against the API's own counts: the six buckets are *this script's* derivation, which classifies each control by precedence. `schemas.GenerateCounts` also counts `already_filled` orthogonally, so its own `already_filled` is larger - 11 run(s) hold a control that is both sensitive and already filled, and the server counts it in both buckets. The per-run reconciliation is asserted in the machine checks. No number above is the server's raw total, and none is meant to be.

**Fabricated claims: 0.** Structurally trivial in offline mode - the stub is a literal extractor and cannot invent, so this zero is about wiring, not about a real model. See sections 6 and 7.

| hard constraint | status |
|---|---|
| H2 no submission | PASS - 0 POST in the access log, 0 values offered for submit-shaped controls |
| H3 no persisted plaintext | PASS - 3 file(s) scanned, 0 hit(s); chrome.storage.local out of reach of a non-browser check |
| H5 no document number | PASS - 42 identity control(s) across the matrix, all sensitive_skipped with no value; canary absent from every response |
| H6 missing means null | PASS - every missing/abstained/sensitive field has suggested_value = null |

Machine checks: 203 L1 check(s) passed before the report.

## 2. Which dimension moves which decision

### 2.1 Form shape (L-A: 6 forms x full_profile x jd_named, everything else held)

| form | dimension under test | controls | offered | abstained | missing | sensitive | not_fillable | already_filled |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| `form_01_baseline` | baseline (reference shape) | 29 | 17 | 0 | 6 | 2 | 4 | 0 |
| `form_02_naming` | field naming style + label source | 30 | 17 | 0 | 6 | 3 | 4 | 0 |
| `form_03_help_text` | help text in <legend> + legend-only field names | 30 | 16 | 0 | 8 | 2 | 4 | 0 |
| `form_04_maxlength` | maxlength tiers 50 / 300 / 1000 | 29 | 17 | 0 | 6 | 2 | 4 | 0 |
| `form_05_traps` | trap controls + page-side pre-fill | 31 | 16 | 0 | 6 | 2 | 6 | 1 |
| `form_06_bilingual` | bilingual labels + Chinese-only labels + contenteditable | 30 | 17 | 0 | 7 | 2 | 4 | 0 |

Reading of 2.1: **form markup has no vote in abstention; it only has a vote in field identification.** `abstained` is 0 in every form variant, and no markup suppresses a tailored answer. Every column that does move moves for a named reason: `missing` where a label stopped being recognisable, `offered` where a control is now refused rather than answered wrongly (section 5 row 1), `not_fillable` where the page had locked a control, whether by `readonly` or by `disabled` (section 5 rows 2 and 3), `sensitive_skipped` where the form simply carries one more identity control, and `already_filled` where the page pre-filled one. The full movement list is below.

Movements against the `form_01_baseline` column, computed from the table above: `form_02_naming` sensitive_skipped +1, `form_03_help_text` offered -1, `form_03_help_text` missing +2, `form_05_traps` offered -1, `form_05_traps` not_fillable +2, `form_05_traps` already_filled +1, `form_06_bilingual` missing +1. Three different things move a cell, and this row is what separates them: a form-shape difference that the dimension under test is supposed to create (the extra sensitive control on `form_02_naming`, the Chinese-only label on `form_06_bilingual`), a control an earlier round now refuses rather than answers wrongly (section 5 rows 1, 2 and 3), and the page-side pre-fill that exists to test edit-wins.

### 2.2 Profile and posting (L-B and L-C)

| run | resume | posting | offered | abstained | missing | sensitive | not_fillable | already_filled | retrieval active |
|---|---|---|---:|---:|---:|---:|---:|---:|---|
| `fm-L-B-form_01_baseline-full_profile-jd_named` | `full_profile` | `jd_named` | 17 | 0 | 6 | 2 | 4 | 0 | yes |
| `fm-L-B-form_01_baseline-sparse_profile-jd_named` | `sparse_profile` | `jd_named` | 9 | 0 | 14 | 2 | 4 | 0 | yes |
| `fm-L-B-form_01_baseline-cross_domain_profile-jd_named` | `cross_domain_profile` | `jd_named` | 15 | 1 | 7 | 2 | 4 | 0 | yes |
| `fm-L-B-form_01_baseline-long_prose_profile-jd_named` | `long_prose_profile` | `jd_named` | 17 | 0 | 6 | 2 | 4 | 0 | yes |
| `fm-L-B-form_01_baseline-minimal_profile-jd_named` | `minimal_profile` | `jd_named` | 3 | 0 | 20 | 2 | 4 | 0 | yes |
| `fm-L-C-form_01_baseline-cross_domain_profile-jd_cross_domain` | `cross_domain_profile` | `jd_cross_domain` | 13 | 3 | 7 | 2 | 4 | 0 | yes |
| `fm-L-C-form_06_bilingual-cross_domain_profile-jd_named` | `cross_domain_profile` | `jd_named` | 15 | 1 | 8 | 2 | 4 | 0 | yes |
| `fm-L-C-form_05_traps-sparse_profile-jd_implied` | `sparse_profile` | `jd_implied` | 8 | 0 | 14 | 2 | 6 | 1 | yes |
| `fm-L-C-form_04_maxlength-long_prose_profile-jd_named` | `long_prose_profile` | `jd_named` | 16 | 0 | 7 | 2 | 4 | 0 | yes |
| `fm-L-C-form_03_help_text-minimal_profile-jd_implied` | `minimal_profile` | `jd_implied` | 3 | 0 | 21 | 2 | 4 | 0 | yes |

Reading of 2.2: abstentions appear in 3 run(s), on profile(s) ['cross_domain_profile'] and posting(s) ['jd_cross_domain', 'jd_named'].
And in each case the withheld fields are the ones whose answer has to be tailored
to the posting (skills, experience, project). The mechanism is visible in the
records: `components_present` carries the retrieved score, and the reason string
names the component that fell under the threshold. Nothing abstains on a
personal or education fact, which is the documented design of
`services._evidence_for_field`. Round 3 narrowed which fields those are: the
employer, job title, internship period and project name are facts about the
candidate rather than answers tailored to the posting, so they are no longer
eligible to abstain (section 5 row 4).

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

The script does not grade L2. It selects the fields and writes the questions; the
generated sheet is 48 lines long. The first time, the verdict column is left empty
for a human to fill. Once filled, the sheet is kept: `l2_review.md` becomes a
read-only record and a later run writes `l2_review.generated.md` instead, because a
filled-in sheet is evidence, not a cache.

The filled sheet's verdict distribution is **agree 7 / disagree 2 / unclear 3**
across twelve fields. Both `disagree` rows and the `agree`-with-wrong-reason row
are handed to section 5 as rows 4 and 5:

- row 4 (`fixed in round 3`) - the experience / project fact split (finding `7a`)
- row 5 (`fixed in round 3`) - the `missing` reason attribution (finding `7b`)

The three `unclear` rows are the three L-A narrative fields, withheld because the
offline stub has no drafting path. That is a mode limit, not a correctness
judgement.

Selected fields and the selection rule are in that file. Note one consequence of H3
that matters for how a reviewer works: the run log holds hashes and lengths, never
values, so L2 cannot be completed from the log alone. It has to be done against a
live panel or a re-run. That is deliberate, not an oversight.

H3 scan coverage, for the record: 3 artifact file(s) and 0 temp file(s) were scanned against 78 sentinel string(s); hits: 0. `chrome.storage.local` status: `not_scanned_outside_a_browser` (section 6, limitation 4).

## 5. Known failures and attribution

Ordered by **severity**, not by discovery order. The rule, stated so it can be argued
with: *user-visible error* (`high`) > *classification gap* (`medium`) > *reporting gap*
(`low`) > *untested* (`low`). A `fixed in round 2` or `fixed in round 3` row is kept
rather than deleted: it was a real failure of an earlier round, and the fix is what the
change log in section 8 records. Three rows are open, all three recorded as design
questions for a later round rather than carried silently.

**Row numbers in this section are display positions**, and a cross-reference that says
`row N` means the Nth row of the table below. Two rows also carry a name from the
round-2 L2 sheet, because that sheet, the regression tests and the change log all use
it: **`7a` is the experience / project fact split and `7b` is the `missing` reason
attribution**. They are written as names and never as `#7a`, so a named row cannot be
mistaken for row 7.

Nine findings: 1 high, 6 medium, 2 low; 5 fixed (in round 2 or round 3), 3 left open (each with the reason it is open), and 1 recorded as not testable in offline mode rather than as open or fixed.

Attribution vocabulary, fixed in advance and unchanged this round: `bug` = the system
produced a wrong result on its own terms; `generation wobble` = the same input gave a
different result; `edge` = a form or data shape outside what the current design claims
to cover. **`generation wobble` is not observable in offline mode (see M3)**, so no row
carries it: the L-D row states why instead.

| # | severity | status | what happened | attribution | evidence |
|---:|---|---|---|---|---|
| 1 | `high` | fixed in round 2 | form_03: the employer control is labelled `Name` inside an `Employer details` section, so the generic name fallback (`_FALLBACK_NAME`) classified it as the candidate's own name and the assistant offered the candidate's full name into the employer box (2 run(s) in round 1). **Round 2:** section text is context and may no longer name a field, so the control is refused (`missing`) rather than filled with the wrong fact. | `bug` | round-1 records: field `name_2`, label `Name`, decision `offered`, source `personal_info.full_name`; round-2 records: decision `missing`; regression `tests/test_form_matrix_regressions.py::test_legend_never_names_a_field`; source `server/field_map.classify` + `extension/src/content.ts:isSectionLevelText` |
| 2 | `medium` | fixed in round 2 | form_05: the `readonly` control was treated as fillable and offered a value - nothing in the skip table or the content script's fillable test knew about readonly (2 run(s), every one `offered` in round 1). **Round 2:** `readonly` is refused at the page (never read, never written) and in `field_map.SKIPPED_ATTRIBUTES`, so the control is `not_fillable` with no value. | `edge` | round-1 records: field `email_readonly`, decision `offered`; round-2 records: decision `not_fillable`, `value_hash` empty; regression `tests/test_form_matrix_regressions.py::test_readonly_control_is_not_fillable`; source `server/field_map.SKIPPED_ATTRIBUTES` + `extension/src/content.ts:isReadonlyControl` |
| 3 | `medium` | fixed in round 3 | form_05: a `disabled` control was treated as fillable, exactly as `readonly` had been. A disabled input is still scanned, and nothing in the skip table or in the content script's fillable test knew about the attribute, so the assistant would offer a value the page can neither edit nor submit. It is the same *family* of mistake round 2 fixed and not a new one, which is the point of listing it. **Round 3:** `disabled` is refused at the page (never read, never written) and in `field_map.SKIPPED_ATTRIBUTES` as a second line of defence; the page-side `type` rules still win, so a `disabled` password field stays a type refusal. | `edge` | regression `tests/test_form_matrix_regressions.py::test_disabled_control_is_not_fillable`; records: field `email_disabled`, decision `not_fillable`, `value_hash` empty; source `server/field_map.SKIPPED_ATTRIBUTES` + `extension/src/content.ts:isDisabledControl`; the control was added to `demo/form_matrix/form_05_traps.html` this round, so rounds 1 and 2 record it as `absent` rather than as a pass |
| 4 | `medium` | fixed in round 3 | `services._evidence_for_field` treated the whole `experience` and `project` categories as posting-tailored, so fact-shaped sub-fields inherited the posting's retrieval score. On a cross-domain posting that score is 0.00 and `Company name` / `Job title` / `Internship period` / `Project name` were withheld (`abstained`) even though the profile states them; the very same fields were `offered` on the same form with an in-domain posting. In the cell where it showed up, 7 fields were withheld and four of them were fact-shaped. **Round 3:** those four moved to `experience_fact` / `project_fact`, which are fact categories, so they use the deterministic extraction confidence instead of the retrieval score. | `bug` | regression `tests/test_form_matrix_regressions.py::test_experience_facts_are_not_tailored`; records: run `fm-L-C-form_01_baseline-cross_domain_profile-jd_cross_domain`, where `Company name` and `Job title` sat on `internship.internship_employer` / `internship.internship_title` and were `abstained` in round 2 and are `offered` now; round-2 L2 sheet question-set-2 rows 5 and 6 (`wf_571f50676d64`, `wf_f551d6320a36`), both `disagree`; source `server/field_map._FIELD_MAP` + `services.FACT_CATEGORIES` |
| 5 | `medium` | fixed in round 3 | a fact-shaped control whose fact is absent from the profile was reported `missing` with the reason `retrieval similarity 0.00 < threshold 0.40`, which sends the user to fix the posting instead of the profile. Nothing had been retrieved for the field, so the reason named a component that was never consulted. The outcome was right and the explanation was wrong, which is why this is a report repair rather than a count movement. **Round 3:** `services._evidence_for_field` returns no evidence at all for a fact category with no fact, and the decision branch reports `no fact in the authorised profile` instead. | `bug` | regression `tests/test_form_matrix_regressions.py::test_missing_reason_names_the_absent_fact`; records: field `gpa`, category `education`, decision `missing`, reason names the absent fact; round-2 L2 sheet question-set-2 row 4 (`wf_f263ef9b690a`) carried the note; source `server/services._evidence_for_field` + `services.MSG_NO_FACT`. The round-2 note also inferred, from `source = "none"`, that the control had never been classified as `education`; the record above shows the category is `education`, so the fix is right for a different reason than the note guessed. Both are stated rather than one being dropped. |
| 6 | `medium` | open - not fixed in this round; recorded as a design question | form_04: a short character limit meets an unbreakable token and the assistant reports the field as unanswerable instead of shortening a URL - which it could do without inventing anything (seen on linkedin (limit 50)) | `edge` | round records, message kind `length_unanswerable`. Not fixed in this round; recorded as a design question - a URL-aware `fit_to_length` would change `server/services.fit_to_length`, which is the pipeline's decision, not this matrix's. |
| 7 | `medium` | open - not fixed in this round; recorded as a design question | form_06: a label written only in Chinese is unclassifiable - `_FIELD_MAP` has no Chinese patterns except in the identity-document block - so '补充说明' is reported missing while its English twin would be answered | `edge` | round records, field `beizhu`, category `unknown`, decision `missing`. Adding Chinese patterns to `_FIELD_MAP` is a classifier decision for the pipeline, not for this matrix. |
| 8 | `low` | open - not fixed in this round; recorded as a design question | form_05: a `<button type="submit">` is invisible to the scanner - the selector matches `input` only - so the panel cannot report it as a refused control. It is also why it cannot be clicked by the assistant, so the effect is a reporting gap, not a safety one | `edge` | form_05 field inventory vs the scan payload: `confirm_application` absent |
| 9 | `low` | not testable in offline mode | L-D: **not testable in offline mode.** The same cell was run 3 time(s) and produced 1 distinct outcome(s) - but the offline stub is a literal extractor: it has no sampler, so any repetition must agree. This is a property of the stub, not evidence that a live model would be stable. | `edge` | run records for L-D compared on (field_id, decision, value_hash). Stability requires `mode=live_api`; it is not claimed by this matrix - see section 6. |

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
- **`disabled` controls are measured now, in one shape only.** Round 3 plants a
  `disabled` input on `form_05_traps` and both layers refuse it (section 5 row 3), so the
  family of mistake behind the round-2 `readonly` finding is closed at the level this
  matrix tests. Still uncovered: a `disabled` `<select>` or `<textarea>`, and a control
  the page disables *after* the scan has run. The matrix plants neither.
- **The page-side half of each fix is unverified in a browser.** The server-side
  refusals and the fact / tailored split are pinned by
  `tests/test_form_matrix_regressions.py`; the content script's own `readonly` and
  `disabled` refusals and its section-context reporting are covered only by
  `scripts/manual_panel_check.md`, and by `extension/scripts/browser_check.mjs` for the
  demo page it drives.
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
| `server/field_map.py` | `32e9b592473b364cb20a84f71b9a78c59d527b3181f385ab33a43655c0f7f23d` |
| `server/services.py` | `96474932066de373949b0fae448f9d47134b58bfde17795157d0b74564641420` |
| `server/schemas.py` | `7c561d9c3a78f17c8c3197afa17ae1e5655f258e525723d52064ab7775627226` |
| `extension/src/content.ts` | `8409886f543c37a28c721f4d68d8d0fc7c55330ea6b5fe29c9272e4a24035619` |

Full digests, not prefixes: this table exists to be recomputed, and a prefix cannot be
checked. The same values are in `artifacts/form_matrix/source_fingerprint.json`, and
both come from one `source_fingerprint()` call, so neither can drift from the files it
names.

Abstention threshold read back: **0.4**, weights
retrieval 0.6 / llm_self 0.4,
abstain-on-either **True**. None of these were changed.

## 7. Live spot-check

Why exactly two runs, and these two. The offline matrix has three blind spots it cannot
close by itself: (a) the classification trap, the section-naming case in section 5 row 1;
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

Live spot-check deferred by scope, not by cost: the two cells are cheap
(of the order of $0.001 each against `openai/gpt-4o-mini`), but a live run
would open a second mode - a real model, a different question - that this
matrix is not structured to carry. Left to the next round; the offline
zero-fabrication figure stays labelled structurally trivial until then.

## 8. Change log - three rounds, cell by cell

Three columns, because two rounds of fixes are stacked on top of each other:
**round 1** is the untouched baseline, **round 2** is the first round of fixes and
**round 3** is this run. Neither before-column is typed in. Both are recomputed from
the run files left on disk (`runs_before_round2.jsonl`, `runs_before_round3.jsonl`)
by the same function that derives the after-column, and that recomputation is
asserted - a transcription that disagreed with the records fails a machine check
instead of printing quietly.

Nothing here was adjusted to make a number read better. A metric that is not in this
table did not move.

| metric | round 1 | round 2 | round 3 | span 1-3 | why it moved |
|---|---:|---:|---:|---|---|
| whole matrix `controls_total` | `561` | `561` | `563` | +2 | +2: the `disabled` input added to `form_05_traps` (section 5 row 3), which appears in two runs |
| whole matrix `offered` | `267` | `263` | `267` | +0 | round 2 lost 4 to two refusals (section 5 rows 1 and 2); round 3 regained 4 from the experience / project fact split (row 4, finding 7a) |
| whole matrix `abstained` | `9` | `9` | `5` | -4 | round 3 only: four fact-shaped sub-fields leave the tailored categories and stop being withheld (row 4, finding 7a) |
| whole matrix `missing` | `165` | `167` | `167` | +2 | round 2: the employer misclassification, 2 runs (section 5 row 1); round 3 moved nothing in or out |
| whole matrix `not_fillable` | `76` | `78` | `80` | +4 | round 2: `email_readonly`, 2 runs (row 2); round 3: `email_disabled`, 2 runs (row 3) |
| whole matrix `sensitive_skipped` | `42` | `42` | `42` | unchanged | unchanged in all three columns: no identity control was added or removed |
| whole matrix `already_filled` | `2` | `2` | `2` | unchanged | unchanged in all three columns: the page-side pre-fill is untouched |
| `form_03_help_text` `offered` | `17` | `16` | `16` | -1 | round 2: the employer control is refused instead of answered with the candidate's name (row 1) |
| `form_03_help_text` `missing` | `7` | `8` | `8` | +1 | the same control; `missing` is the only bucket an `offered` loss can land in |
| `form_05_traps` `controls_total` | `30` | `30` | `31` | +1 | round 3: the `disabled` control is added to the page |
| `form_05_traps` `offered` | `17` | `16` | `16` | -1 | round 2: the `readonly` control is refused (row 2) |
| `form_05_traps` `not_fillable` | `4` | `5` | `6` | +2 | round 2: `readonly` (row 2); round 3: `disabled` (row 3) |
| `form_01_baseline` x `cross_domain_profile` `offered` (L-C) | `9` | `9` | `13` | +4 | round 3: the four fact-shaped sub-fields are offered as facts instead of withheld as tailored (row 4, finding 7a) |
| `form_01_baseline` x `cross_domain_profile` `abstained` (L-C) | `7` | `7` | `3` | -4 | the same four fields (row 4, finding 7a) |
| `name_2` decision | `offered` | `missing` | `missing` | changed | round 2, and unchanged since: `offered` -> `missing` (row 1) |
| `email_readonly` decision | `offered` | `not_fillable` | `not_fillable` | changed | round 2, and unchanged since: `offered` -> `not_fillable` (row 2) |
| `email_disabled` decision | `absent` | `absent` | `not_fillable` | changed | round 3: the control did not exist before this round (row 3) |

Every row that moved, and why the move is forced rather than chosen:

- **Finding `7a` (section 5 row 4) moved four fields, in exactly one run.** `Company
  name`, `Job title`, `Internship period` and `Project name` are facts the profile
  states, not answers tailored to a posting, so they left
  `services.TAILORED_CATEGORIES` and stopped inheriting the posting's retrieval
  score. All four were `abstained` in exactly one cell - `fm-L-C-form_01_baseline-cross_domain_profile-jd_cross_domain`
  - so that run gains 4 `offered` and loses 4 `abstained`. Those eight cells are the
  whole of its effect on the matrix; the other eight runs are byte-identical in
  their decision counts.
- **Finding `7b` (section 5 row 5) moved no count at all.** A fact-shaped field whose
  fact is absent from the profile was already `missing`, so the fix changes the
  *reason* it reports and the components it claims to have measured. It is listed
  here as a report repair rather than a number, because claiming a count movement
  for a change that only touched a string would be a fabrication.
- **The `disabled` fix (section 5 row 3) added a control.** The input on
  `form_05_traps` appears in two runs, so it adds 2 to the field total and 2 to
  `not_fillable`, and 0 to `offered` - which is why the eligible denominator (439)
  does not move at all.

One round-2 prediction could not hold, and it is arithmetic rather than opinion. The
round-2 brief expected `form_03 offered` to fall 17 -> 16 **and** `form_03 missing` to
fall 7 -> 6 at the same time. The field total for that form is fixed, `abstained` and
`sensitive_skipped` cannot move in offline mode, and `not_fillable` is unchanged on
form_03 - so a control leaving `offered` has exactly one bucket left to land in, and
it is `missing`. The recorded outcome was `offered` 17 -> 16 with `missing` 7 -> 8, and
round 3 disturbed neither column.

`abstained` did move this round, 9 -> 5, and every field it lost is named above; the
five that remain are `skills` / `experience` / `project` fields whose answer genuinely
has to be tailored, which is what abstention is for.

Three things changed in the *report* itself without a count changing. Each repairs an
earlier round rather than editing it quietly:

- Round 1's section 2.1 called `sensitive_skipped` constant across form variants. It is
  not: `form_02_naming` carries 3 identity controls where every other form carries 2, so
  the column moves by +1 there. The reading now names that cause instead of denying it,
  and the movement list under the table enumerates it.
- The fingerprint table prints the full digest. A 16-character prefix cannot be
  recomputed against the file it names, and a table that cannot be checked is decoration.
- Round 2's L2 sheet inferred, from `source = "none"`, that the classifier had *never*
  placed the absent GPA control in the education category. The record says otherwise:
  the category is `education`, and the field is `missing` because the profile carries no
  GPA - which is exactly what finding `7b` now says out loud. The finding was right
  about the symptom and wrong about the mechanism, and both halves are recorded here
  rather than letting a wrong explanation stand next to a correct fix.

