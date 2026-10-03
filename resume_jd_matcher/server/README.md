# `server/` — the local backend for the browser assistant

A thin HTTP layer over the existing `src/` pipeline. It exists so the Chrome
extension has something to talk to; it does not contain a second copy of any
decision the pipeline already makes.

```
server/
├── __init__.py     module docstring: the one-directional import graph
├── app.py          FastAPI app, the five routes, token gate, loopback assertion
├── schemas.py      Pydantic v2 request/response models
├── services.py     orchestration: scan / analyse_jd / generate
├── field_map.py    web-form classification, profile rendering, deterministic facts
├── jd_fetch.py     job-posting reader (SSRF-guarded, robots-respecting)
└── security.py     loopback bind assertion, token, CORS origin regex
```

## 1. Running it

```bash
cd resume_jd_matcher
pip install -r requirements.txt

# offline: no API key, no network, deterministic. Everything below works today.
RJD_OFFLINE=1 python -m server.app            # binds 127.0.0.1:8765

# live: real model calls via OpenRouter (reads resume_jd_matcher/.env)
python -m server.app --port 8765
```

The token is generated on first run into `artifacts/server_token.txt` (mode
`0600`) and printed at startup. Every route except `/health` requires it in the
`X-RJD-Token` header. `RJD_SERVER_TOKEN` overrides it.

> The server refuses to bind anything but a loopback address. `assert_loopback`
> raises `InsecureBindError` at startup, and `--host` cannot talk it out of that.
> Binding to `0.0.0.0` would put a service holding the user's resume on the LAN.

## 2. Endpoints

| Route | Purpose | Auth |
|---|---|---|
| `GET /health` | liveness + mode + token policy + sensitive-field policy | no |
| `POST /scan` | normalise and classify a page's controls | yes |
| `POST /generate` | draft suggestions for a page's fields | yes |
| `POST /jd/fetch` | read a public job posting's text | yes |
| `POST /jd/analyze` | analyse a pasted posting | yes |
| `POST /extract_resume` | read a profile out of resume text the panel already extracted | yes |

There is **no write endpoint and no submit endpoint.** Filling a page happens
entirely inside the browser: the extension sends values to its own content
script, which is the only code that touches the DOM. `scripts/e2e_check.py` and
`scripts/run_form_matrix.py` assert that the API surface stays exactly these six
routes.

`/extract_resume` is the sixth route and is **not** an exception to the rule
above: it takes text and returns a profile, and it persists nothing. There is no
document upload — the extension parses the PDF in the browser with PDF.js and
sends only the text, so this route exists precisely so that the server never
needs a file-handling surface. See `extension/README.md` section 8.

`/health` is deliberately unauthenticated and deliberately free of user data: the
extension must learn whether the backend is up, what mode it is in and whether a
token will be required *before* it can send anything.

## 3. Where each decision lives

The rule this package is written to obey: **there is exactly one implementation
of every decision.** Nothing under `server/` re-implements the abstention rule,
the fabrication guards, the similarity calibration, the prompt-hijack sanitiser
or the retrieval scoring.

| Decision | Lives in |
|---|---|
| abstention arithmetic | `src/pipeline/confidence.assess` |
| per-field withholding | `src/pipeline/confidence.field_level_abstentions` |
| literal-value fabrication | `src/llm/extractor.FabricationGuard` |
| skill-claim fabrication | `src/taxonomy.has_lexical_support` |
| similarity rescaling | `src/retrieval/store.KnowledgeBase.retrieve` |
| untrusted-JD hygiene | `src/sanitize.prepare_untrusted` / `wrap_untrusted` |
| retrieval query shape | `src/pipeline/runner.build_retrieval_query` |
| offline behaviour | `src/llm/offline.run_stub` |
| condition A's answer | a deterministic copy — no model is called |

Two decisions *do* belong to this layer. Both are stated in full rather than
left implicit, because a reader has to be able to disagree with them.

### 3.1 Which confidence components a field gets (`services._evidence_for_field`)

The task fixes the formula and the threshold; it does not say what the
`retrieval` slot should carry for a field the posting has nothing to do with.

- A field whose answer must be **tailored** to the posting (narrative, skills,
  experience, project) gets the posting's retrieval score. Under a model-only
  condition there is no retrieval, so the slot is **absent** rather than filled
  with something else.
- A field that is a **plain fact about the person** (personal, education) gets
  the deterministic extraction confidence instead.

Without the second rule, an unrelated posting would make the assistant abstain on
the candidate's own email address — not a confidence judgement anybody could
defend.

> This used to fall back to the fact confidence for tailored fields too. That was
> wrong twice over: it disagreed with the evaluation's definition of condition B,
> and it mislabelled the number — a B run reported
> `components_present == ["retrieval"]` when no retrieval had happened. See §6.

### 3.2 How prose is checked for fabrication (`services.NarrativeGuard`)

`FabricationGuard` asks "does this literal value appear in the source?", which is
the right question for a name or a school and the wrong one for a paragraph: no
honest cover letter is composed only of words that appear in a profile, so
applying it to prose would withhold every draft.

Prose is checked for **claims** instead — numbers, multi-word proper names, and
skill names — and all three use word-boundary matching.

**Known gap, stated rather than hidden:** a *single* capitalised token is not
checked, because telling an invented city from the pronoun "I" without a
gazetteer is not something a regex can do. Multi-word names — where invented
employers and institutions actually appear — are checked, every narrative field
is marked `needs_user_confirmation`, and nothing is written until the user
clicks. See `tests/test_server_generate.py::test_a_single_capitalised_token_is_a_documented_gap`.

## 4. The two hard rules

§4.1 and §4.2 are the two rules. §4.3 is not a third one: it defines a single
word inside §4.1 — *transmitted* — so that claim can be measured instead of
asserted.

### 4.1 Extremely sensitive fields are never collected, generated or transmitted

Matched by `field_map.SENSITIVE_PATTERNS`: passport, national identity / ID card
/ NRIC / MyKad / Aadhaar / PAN, social security, residence permit, tax
identification, driving licence, and the Chinese spellings.

The rule is enforced at four boundaries, because holding at three of them is not
the rule the task asks for:

| Boundary | What happens | Test |
|---|---|---|
| scan response | the field is flagged; its value is **dropped** | `test_document_numbers_are_not_echoed_in_the_scan_response` |
| model prompt | the field is absent from the field list entirely | `test_no_document_number_reaches_any_prompt` |
| generate response | no value, `sensitive_skipped=true`, one plain message | `test_no_sensitive_field_gets_a_suggested_value` |
| persisted drafts | nothing to persist — the value never entered the response | `test_a_document_number_typed_on_the_page_is_not_echoed_back` |

Two deliberate calls:

- **driving-licence number is included** — same class of government-issued
  identifier as a passport number;
- **student / application / candidate / employee ID are NOT included** — they are
  institution- or employer-issued, commonly asked for, and blocking them would
  suppress answers users need. `SAFE_ID_PATTERNS` is checked *before*
  `SENSITIVE_PATTERNS` so `StudentID` does not trip the generic `id number` rule.

The classifier splits camelCase before matching, because DOM attributes are
routinely camelCase: `id="passportNo"`, `id="idNumber"` and `id="NRICNumber"` are
the spellings a real form uses, and without the split they normalised to
`passportno` / `idnumber` / `nricnumber` and matched nothing.

### 4.2 Missing information is never fabricated

- A field with no grounded value is reported `missing=true` with a message, and
  `suggested_value` is `null`. **`null`, never `""`** — those are different
  states, and collapsing them would let a skipped passport field look like an
  intentional blank.
- A select/radio answer is snapped onto the control's own options, or refused.
  Writing a value the control does not offer means the browser silently discards
  it and the user is told "filled" and then sees an empty field.
- A draft the guards reject falls back to the profile's own literal, or is
  withheld — never quietly rewritten into something the model did not write.

### 4.3 Definition of "transmitted" in H5

H5 says a document number is never transmitted. That word needs a definition
before the claim can be measured, because a flat "the value never leaves the
page" would be false:

> A value counts as **transmitted** when it leaves this machine, when it reaches
> a model or any third party, or when it is written to durable storage.
>
> It does **not** count as transmitted when it stays in memory *on this machine*
> and is dropped before any of those three things happens.

Under that definition the four boundaries in §4.1 are what make H5 true, and
exactly one of the hops is measured rather than given by construction:

| Hop | Transmitted? | Why |
|---|---|---|
| page → content script | no | the value stays in the browser's own process memory |
| content script → `127.0.0.1` | **yes — this is the measured hop** | the value crosses the loopback socket in the `/scan` and `/generate` request bodies |
| request body → model prompt | no | the field is absent from the field list entirely (§4.1) |
| model response → panel → disk | no | nothing to persist: no value is ever returned (§4.1) |

So the honest statement of H5 is **"never leaves the machine, never reaches a
model and never reaches a third party"** — not "never touches the wire". A
document number that is already typed into a page *does* reach the local server
process. There it is dropped in `normalise_fields`, which sets
`current_value=""` for every `sensitive` field, so the value is never used as a
value, never placed in a prompt, never echoed to the panel and never written to
disk. Only `password` and `file` are refused earlier than that, by the content
script's own never-read list.

Why that boundary is the reasonable one:

- sender and receiver are the same machine, over a loopback socket that
  `security.assert_loopback` pins and that `--host` cannot move;
- a value already on the user's screen has not been handed to a third party by
  being read into a helper the user installed themselves;
- refusing the hop outright means the assistant can no longer tell *"this page
  already holds a passport number"* from *"this page asks for one"* — and the
  second fact is the one the guard has to see.

Residual risk, named rather than waved away: **any process already running on
this machine could observe that loopback socket.** The design that would close
it is a two-phase scan — collect field *shapes* first, then read *values* only
for the fields the server did not refuse. That is a change to the content
script, not a setting, so it is recorded as a design question rather than
claimed as covered.

## 5. Response schema

`FieldSuggestion` is a **strict superset** of the specified schema. The specified
keys are all present with the specified types and defaults:

```
field_id, label, type, required, max_length, suggested_value, source,
jd_relevance, confidence, components_present, needs_user_confirmation,
missing, sensitive_skipped, message
```

Additive keys, needed to drive a browser rather than to satisfy the schema:

| Key | Why it exists |
|---|---|
| `tag`, `selector` | so the content script can find the DOM node again |
| `current_value`, `already_filled` | so the panel can show what the user typed and honour edit-wins |
| `options` | so the panel can show why a select was refused |
| `abstained`, `reasons` | so a withheld value can say *why* it was withheld |
| `fillable` | `false` for a control we never touch — the panel must not offer a fill action |

`GenerateCounts` partitions every field across
`suggestion_offered + withheld_low_confidence + missing + sensitive_skipped +
not_fillable == total`. `already_filled` is a separate, orthogonal count: a field
the user filled can also be one we refuse, so it deliberately overlaps.

`abstained` means one thing only: *the confidence rule withheld a candidate
value*. `missing` means *no value is on offer for any other reason*. They are
never both set.

## 6. `POST /jd/fetch` — what it refuses

This is the only route that opens a network connection, so it refuses more than
it does.

| Refusal | Reason code |
|---|---|
| scheme is not http/https, or no host | `unsupported_scheme` |
| host resolves to loopback / private / link-local / reserved / multicast | `private_host` |
| host does not resolve at all | `private_host` |
| a redirect hop lands on a non-public address | `private_host` |
| `robots.txt` disallows the path | `robots_disallowed` |
| HTTP 401 | `login_required` |
| HTTP 402 | `paywall` |
| HTTP 403 / 429 | `blocked` |
| any other HTTP ≥ 400 | `http_error` |
| body > 2 MB | `too_large` |
| content-type is not HTML or text | `not_html` |
| gate markers (sign-in / paywall / captcha / blocked) on a page too short to be a posting | that marker |
| timeout / connection failure | `timeout` / `network_error` |

Every refusal carries a `message` telling the user to paste the posting text
instead. The gate markers are only consulted when the extracted text is shorter
than 200 characters, so an ordinary posting with a "subscribe to our newsletter"
footer is not misread as a paywall.

The SSRF check is by **resolved address**, not by hostname, and it is repeated on
every redirect hop — following a redirect blindly is the standard way that guard
gets bypassed. `tests/test_jd_fetch.py` drives all of it with an injected
`fetch`/`resolve`, so no test touches the network.

## 7. Privacy

- **Nothing is written to disk.** The response says so:
  `privacy.in_memory_only = true`, `privacy.persisted = false`.
- **No raw user text is logged.** `RJD_SERVER_LOG=1` (default **off**) enables a
  fingerprinted action log at `artifacts/agent_actions.jsonl` containing counts
  and `sha256` prefixes only — the same convention `src/logging_utils.py`
  enforces for evaluation runs. A `jd_url` is recorded as a hash, because a URL
  routinely carries an applicant identifier.
- **Un-ticked modules are stripped server-side.** The browser must not send them,
  and the server refuses them if it does: `render_profile` only renders the
  authorised modules, and `privacy.dropped_modules` says what it removed. The
  model input *is* the guard's haystack, so an un-ticked module cannot leak into
  an answer even if the client sends it.
- **The retrieval index lives in `artifacts/server_index/`**, separate from any
  evaluation run's `--out-dir`, so the two can never delete each other's index.

## 8. What is verified, and what is not

Verified on 2026-09-25, on this machine:

- `python -m unittest discover -s tests -t .` → **267 tests, OK** (109 pre-existing
  + 158 for the backend).
- `python scripts/e2e_check.py` → **131/131 checks**, running the real server on a
  loopback port against `demo/application_form.html`.
- `python scripts/smoke_check.py` → passed. `python scripts/ui_headless_check.py`
  → 16/16.
- Every refusal branch in §6, driven with an injected fetcher.

**Not verified:**

- **Answer quality.** `scripts/e2e_check.py` runs against the deterministic
  offline stub. It shows the wiring is correct and that the two hard rules hold
  on that page; it is not evidence about a real model's answers.
- **Label resolution in a real browser.** `e2e_check.py` re-implements the
  content script's DOM extraction in Python. It is an approximation; the content
  script itself is covered by `tsc --noEmit`, by `vite build` (which asserts it is
  still a classic script), and by `scripts/ui_headless_check.py`.
- **A live run with an API key.** No live `/generate` call has been made through
  this server. The offline path is what has been exercised.
