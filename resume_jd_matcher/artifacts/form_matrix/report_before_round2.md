# Form matrix - browser assistant under field and profile diversity

Driver: `scripts/run_form_matrix.py`. Runs: **19**. Controls seen: **561**.
Condition: **C** (retrieval + model). Server mode: **offline_stub** for every run.

Scope, stated first: this matrix drives the assistant's own HTTP contract
(`/scan` then `/generate`) with the content script's DOM extraction mirrored in
Python. It is not a browser run. Answer quality is not measurable here, because
the offline stub is a literal extractor, not a model.

## 1. Headline (counts)

Decision distribution over every control in every run. Counts are the headline;
percentages are supplementary.

| decision | fields | share | runs containing at least one |
|---|---:|---:|---:|
| `offered` | 267/561 | 47.6% | 19/19 |
| `abstained` | 9/561 | 1.6% | 3/19 |
| `missing` | 165/561 | 29.4% | 19/19 |
| `sensitive_skipped` | 42/561 | 7.5% | 19/19 |
| `not_fillable` | 76/561 | 13.5% | 19/19 |
| `already_filled` | 2/561 | 0.4% | 2/19 |

**Fabricated claims: 0.**

| hard constraint | status |
|---|---|
| H2 no submission | PASS - 0 POST in the access log, 0 values offered for submit-shaped controls |
| H3 no persisted plaintext | PASS - 3 file(s) scanned, 0 hit(s); chrome.storage.local out of reach of a non-browser check |
| H5 no document number | PASS - 42 identity control(s) across the matrix, all sensitive_skipped with no value; canary absent from every response |
| H6 missing means null | PASS - every missing/abstained/sensitive field has suggested_value = null |

Machine checks: 167 L1 check(s) passed before the report.

## 2. Which dimension moves which decision

### 2.1 Form shape (L-A: 6 forms x full_profile x jd_named, everything else held)

| form | dimension under test | controls | offered | abstained | missing | sensitive | not_fillable | already_filled |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| `form_01_baseline` | baseline (reference shape) | 29 | 17 | 0 | 6 | 2 | 4 | 0 |
| `form_02_naming` | field naming style + label source | 30 | 17 | 0 | 6 | 3 | 4 | 0 |
| `form_03_help_text` | help text in <legend> + legend-only field names | 30 | 17 | 0 | 7 | 2 | 4 | 0 |
| `form_04_maxlength` | maxlength tiers 50 / 300 / 1000 | 29 | 17 | 0 | 6 | 2 | 4 | 0 |
| `form_05_traps` | trap controls + page-side pre-fill | 30 | 17 | 0 | 6 | 2 | 4 | 1 |
| `form_06_bilingual` | bilingual labels + Chinese-only labels + contenteditable | 30 | 17 | 0 | 7 | 2 | 4 | 0 |

Reading of 2.1: no form-shape dimension produces an abstention, and the only dimension that moves `missing` is *field naming and help-text placement*, because a control the classifier cannot name cannot be answered at all. That is the expected shape - abstention is a confidence judgement about the posting and the profile, and form markup has no vote in it.

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
| `fm-L-C-form_05_traps-sparse_profile-jd_implied` | `sparse_profile` | `jd_implied` | 9 | 0 | 14 | 2 | 4 | 1 | yes |
| `fm-L-C-form_04_maxlength-long_prose_profile-jd_named` | `long_prose_profile` | `jd_named` | 16 | 0 | 7 | 2 | 4 | 0 | yes |
| `fm-L-C-form_03_help_text-minimal_profile-jd_implied` | `minimal_profile` | `jd_implied` | 4 | 0 | 20 | 2 | 4 | 0 | yes |

Reading of 2.2: abstentions appear in 3 run(s), on profile(s) ['cross_domain_profile'] and posting(s) ['jd_cross_domain', 'jd_named'].
and in each case the withheld fields are the ones whose answer has to be tailored
to the posting (skills, experience, project). The mechanism is visible in the
records: `components_present` carries the retrieved score, and the reason string
names the component that fell under the threshold. Nothing abstains on a
personal or education fact, which is the documented design of
`services._evidence_for_field`.

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
never appears in any response body in any run. One boundary is measured rather than
assumed and is reported honestly: the content script's never-read list covers
`password` and `file` only, so a document number that is already typed into a page
**does** cross the loopback boundary to the local server, which then drops it. It is
never sent to a model, never echoed to the panel, never used as a value and never
written to disk. Whether it should be withheld at the page as well is a design
question this matrix raises and does not settle.

## 4. L2 - what a human still has to judge

The script does not grade L2. It selects the fields and writes the questions to
`artifacts/form_matrix/l2_review.md`, with the verdict column left empty.

Selected fields and the selection rule are in that file. Note one consequence of H3
that matters for how a reviewer works: the run log holds hashes and lengths, never
values, so L2 cannot be completed from the log alone. It has to be done against a
live panel or a re-run. That is deliberate, not an oversight.

`l2_review.md` is 40 lines long.

H3 scan coverage, for the record: 3 artifact file(s) and 0 temp file(s) were scanned against 78 sentinel string(s); hits: 0. `chrome.storage.local` status: `not_scanned_outside_a_browser`.

## 5. Known failures and attribution

| # | what happened | attribution | evidence |
|---:|---|---|---|
| 1 | form_03: the employer control is labelled `Name` and named by its legend, so the generic name fallback classifies it as the candidate's own name and the assistant offers the candidate's full name into the employer box (2 run(s)) | `bug` | run records, field `name_2`, label `Name`, decision `offered`, source `personal_info.full_name` |
| 2 | form_04: the 50-character LinkedIn limit meets an unbreakable token and the assistant reports the field as unanswerable instead of truncating a URL | `edge` | run records, field `linkedin`, message kind `length_unanswerable` |
| 3 | form_05: the `readonly` control is treated as fillable and is offered a value; nothing in the skip table or the content script's fillable test knows about readonly | `edge` | run records, field `email_readonly`, decision `offered` |
| 4 | form_05: a `<button type="submit">` is invisible to the scanner - the selector matches `input` only - so the panel cannot report it as a refused control. It is also why it cannot be clicked by the assistant, so the effect is a reporting gap, not a safety one | `edge` | form_05 field inventory vs the scan payload: `confirm_application` absent |
| 5 | form_06: a label written only in Chinese is unclassifiable - `_FIELD_MAP` has no Chinese patterns except in the identity-document block - so '补充说明' is reported missing while its English twin would be answered | `edge` | run records, field `beizhu`, category `unknown`, decision `missing` |
| 6 | L-D: the same cell run 3 times produced one identical outcome, so no generation wobble was observed in the offline path | `edge` | run records for L-D compared on (field_id, decision, value_hash) |

Attribution vocabulary, fixed in advance: `bug` = the system produced a wrong result
on its own terms; `generation wobble` = the same input gave a different result;
`edge` = a form or data shape outside what the current design claims to cover.

## 6. Limitations

- **Not a browser run.** The content script's extraction is mirrored in Python. The
  real content script is verified separately by `extension/scripts/browser_check.mjs`.
- **Offline stub only.** `RJD_OFFLINE=1` for every run, so the drafting is a literal
  extractor. `fabricated_claims == 0` therefore says the guards and the wiring hold on
  this data - it is **not** evidence that a live model would not fabricate. Only a
  `mode: live_api` matrix could say that, and it would cost money per run.
- **Dimensions not covered.** No unsaved-draft flow, no multi-step wizard, no
  same-name repeated controls across sections, no dynamically inserted fields, no
  iframe or shadow DOM, no `<button>`-based form controls beyond the one absence
  recorded in section 5, no non-Latin label tested beyond Chinese, and no right-to-left
  text. The `readonly` observation in section 5 was reasoned from the DOM contract and
  was not verified in a browser.
- **Corpus limit still standing.** The similarity scale is the one already documented
  for the same 54-chunk knowledge base (floor 0.3663, ceiling 0.5633). The knowledge
  base was not rebuilt and `scripts/calibrate_similarity.py` was not run, so no
  recalibration is being claimed. Change the corpus and these numbers are void.
- **Timing metrics remain disabled** (H8). No duration appears anywhere in this
  report, and none was measured.
- **Side panel rendering is covered by the manual checklist, not by this script.**
  `scripts/manual_panel_check.md` is the procedure; `chrome.sidePanel.open()` refuses
  a synthetic gesture, which is why it cannot be automated.
- **chrome.storage.local was not inspected.** It only exists inside a browser
  extension context, so this script cannot read it. The manual checklist includes it.

Source fingerprint (H7):

| file | sha256 |
|---|---|
| `config.yaml` | `a787ab8f60b875dc...` |
| `src/pipeline/confidence.py` | `0e06e38d720462ce...` |
| `src/rules/fields.py` | `aab029a1e633dce5...` |
| `src/taxonomy.py` | `9a52510e34cb29a2...` |
| `src/retrieval/store.py` | `ecf4c6b6b2b451c2...` |
| `src/llm/extractor.py` | `73bfaa0e4faebe00...` |
| `src/llm/offline.py` | `0278f7efe1bfc500...` |
| `src/sanitize.py` | `8e97d716cb32be54...` |
| `server/field_map.py` | `c613e53b27ac1383...` |
| `server/services.py` | `ea64fed1b89e8709...` |
| `server/schemas.py` | `0fced47b28da1352...` |

Abstention threshold read back: **0.4**, weights
retrieval 0.6 / llm_self 0.4,
abstain-on-either **True**. None of these were changed.

