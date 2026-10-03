# L2 - human judgement sheet

Not graded by the script. Fill the last two columns in by hand.

Selection rule: the first run of L-A and the first run of L-C in run order, then the
first three fields of each whose decision is `offered`, taken in field order. Fields
are chosen this way so the reviewer spends their attention on values that were actually
offered, which is where a wrong answer would reach a user.

Values are **not** in this file: the run log stores a hash and a length only (H3).
To judge a row, re-run the same cell and read the panel, or read the live page.
Reproduce the *questions* with:

```
python scripts/run_form_matrix.py
```

This file is hand-filled once and is never overwritten while it carries verdicts;
a later run writes `l2_review.generated.md` instead.

## Question set 1 - fields the system offered

Question for every row: *does this value really come from the candidate's profile,
and is it in the correct field? Should it have been withheld instead?*

| run_id | field_id | label | system_decision | system_reason | question for the reviewer | verdict | note |
|---|---|---|---|---|---|---|---|
| `fm-L-A-form_01_baseline-full_profile-jd_named` | `wf_409c03990f25` | Full name | `offered` | (no reason string on this row) | Does this value really come from the candidate's profile, and is it in the correct field? Should it have been withheld (abstained/missing) instead? | | |
| `fm-L-A-form_01_baseline-full_profile-jd_named` | `wf_36bfd748fcd2` | Email address | `offered` | (no reason string on this row) | Does this value really come from the candidate's profile, and is it in the correct field? Should it have been withheld (abstained/missing) instead? | | |
| `fm-L-A-form_01_baseline-full_profile-jd_named` | `wf_459eca7fb38d` | Phone | `offered` | (no reason string on this row) | Does this value really come from the candidate's profile, and is it in the correct field? Should it have been withheld (abstained/missing) instead? | | |
| `fm-L-C-form_01_baseline-cross_domain_profile-jd_cross_domain` | `wf_409c03990f25` | Full name | `offered` | (no reason string on this row) | Does this value really come from the candidate's profile, and is it in the correct field? Should it have been withheld (abstained/missing) instead? | | |
| `fm-L-C-form_01_baseline-cross_domain_profile-jd_cross_domain` | `wf_36bfd748fcd2` | Email address | `offered` | (no reason string on this row) | Does this value really come from the candidate's profile, and is it in the correct field? Should it have been withheld (abstained/missing) instead? | | |
| `fm-L-C-form_01_baseline-cross_domain_profile-jd_cross_domain` | `wf_459eca7fb38d` | Phone | `offered` | (no reason string on this row) | Does this value really come from the candidate's profile, and is it in the correct field? Should it have been withheld (abstained/missing) instead? | | |

## Question set 2 - fields the system refused

These are the fields where the system declined. The question is the inverse: was
refusing right, or did it withhold something the profile plainly states?

| run_id | field_id | label | system_decision | system_reason | question | verdict | note |
|---|---|---|---|---|---|---|---|
| `fm-L-A-form_01_baseline-full_profile-jd_named` | `wf_4ba3bef9d2b3` | Why do you want this role? | `missing` | only the retrieval component exists for this condition; confidence equals that c | Was refusing right - and does the profile actually hold that answer? | | |
| `fm-L-A-form_01_baseline-full_profile-jd_named` | `wf_cf2dbc97045a` | Cover letter | `missing` | only the retrieval component exists for this condition; confidence equals that c | Was refusing right - and does the profile actually hold that answer? | | |
| `fm-L-A-form_01_baseline-full_profile-jd_named` | `wf_628fecac04fd` | Additional information | `missing` | only the retrieval component exists for this condition; confidence equals that c | Was refusing right - and does the profile actually hold that answer? | | |
| `fm-L-C-form_01_baseline-cross_domain_profile-jd_cross_domain` | `wf_f263ef9b690a` | GPA | `missing` | no fact in the authorised profile answers this field; nothing was drafted and no | Was refusing right - and does the profile actually hold that answer? | | |
| `fm-L-C-form_01_baseline-cross_domain_profile-jd_cross_domain` | `wf_9c671102f95e` | Describe your internship | `abstained` | combined confidence 0.22 < threshold 0.40; retrieval similarity 0.00 < threshold | Was refusing right - and does the profile actually hold that answer? | | |
| `fm-L-C-form_01_baseline-cross_domain_profile-jd_cross_domain` | `wf_6e80cf27e634` | Project description | `abstained` | combined confidence 0.22 < threshold 0.40; retrieval similarity 0.00 < threshold | Was refusing right - and does the profile actually hold that answer? | | |

