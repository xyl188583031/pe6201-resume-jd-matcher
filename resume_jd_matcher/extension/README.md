# `extension/` — the Chrome side-panel assistant (Manifest V3)

A Manifest V3 extension that reads a job-application form, asks the local
backend for drafts, and writes only what the user approves. **It never submits
anything.**

```
extension/
├── manifest.json           MV3 manifest (source of truth; copied into dist/ at build)
├── package.json            React 18 + Vite 5 + TypeScript 5 (strict)
├── tsconfig.json           strict, noUnusedLocals, noUnusedParameters
├── vite.config.ts          two entry points + a stable-name build for the worker/script
└── src/
    ├── types.ts            mirrors server/schemas.py
    ├── storage.ts          chrome.storage.local wrapper; strips document numbers before persisting
    ├── api.ts              the ONLY code in the extension that makes a network call
    ├── background.ts       service worker: routes panel messages, owns the network
    ├── content.ts          page-side: scans controls, writes values, never submits
    └── sidepanel/
        ├── main.tsx
        ├── App.tsx         state machine: authorise → profile → scan → JD → generate → review → fill
        ├── labels.ts       the one bilingual zh/en table every panel string comes from
        ├── pdf.ts          PDF.js in the browser: a resume becomes text, never an upload
        ├── styles.css
        ├── hooks/
        │   └── useLabel.ts the shared language store behind every caption
        └── components/
            ├── StatusBanner.tsx
            ├── AuthorisationPanel.tsx
            ├── LanguageToggle.tsx
            ├── ProfileForm.tsx
            ├── ResumeUpload.tsx
            ├── JdPanel.tsx
            ├── FieldTable.tsx
            └── FieldRow.tsx
```

## 1. Build and load

```bash
cd extension
npm install
npm run build          # tsc --noEmit && vite build  -> dist/
```

Then in Chrome: `chrome://extensions` → Developer mode → **Load unpacked** →
select `extension/dist`.

Start the backend first (see `server/README.md`). The extension talks only to
`http://127.0.0.1:8765`; `host_permissions` lists loopback and nothing else.

Other scripts:

```bash
npm run typecheck      # tsc --noEmit only
npm run watch          # rebuild on change
npm run clean          # remove dist/
```

`vite.config.ts` does three non-obvious things:

- **copies `manifest.json` into `dist/`**, so the loaded extension always matches
  the source manifest;
- **emits `background.js` and `content.js` with stable, unhashed names**, because
  `manifest.json` names them literally. A hashed filename would break the
  manifest silently;
- **copies PDF.js's worker into `dist/pdf.worker.js`**, which `pdf.ts` registers by
  extension URL. It is copied verbatim and has to be: PDF.js v6 always constructs
  the worker with `{ type: "module" }`, so the file stays an ES module, and because
  its URL is same-origin with the panel, PDF.js loads it directly instead of
  wrapping it in the blob it uses for cross-origin workers. Shipping it inside the
  extension is what keeps resume reading offline. The manifest needs no
  `web_accessible_resources` entry for it: the panel loads its own origin's
  resources.

The content script must be a **classic script** — it may not contain `import` or
`export`. Vite would normally emit an ES module, so the build is configured to
avoid that and `scripts/e2e_check.py` asserts it: a content script that becomes a
module fails to load, and the only symptom is "the extension does nothing".

## 1.5 Interface language

One control, top-right, three states: **ZH**, **EN**, **ZH+EN** (bilingual — the
default, and the behaviour the panel had before the switch existed).

- Every panel string is a `{zh, en}` pair in `labels.ts`, and no component renders
  a literal. `useLabel()` resolves a key against the current language, so "there is
  no Chinese left in English mode" is something a check can scan the DOM for rather
  than a claim about how carefully the components were written.
- The three captions are ASCII on purpose: `ZH`, `EN`, `ZH+EN` rather than the
  Chinese endonyms. A switcher lettered in Chinese would put Chinese glyphs on
  screen in English mode, which would force the browser check to carve out an
  exception for exactly the control the check exists to prove.
- **Three namespaces, one lookup**: a bare key is a panel string, `field.<key>` is a
  profile input's caption, `module.<name>` is an authorisable module's name. The
  prefixes are load-bearing rather than tidy — `location` means the *posting's*
  location in the JD analysis and the *candidate's* own on the profile form, and a
  flat lookup silently resolved one to the other's wording.
- The chosen language lives under its own storage key (`uiLanguage`), **not** inside
  `rjd_state_v1`. The two have different lifetimes: clearing the profile must not
  reset a reading preference, and switching language must not rewrite saved profile
  data.
- The state is a module-level store read through `useSyncExternalStore`, not a React
  context. The control is mounted once while seven sibling components render the
  strings it changes, so per-component state would repaint the control and nothing
  else; a context would work but would add a provider every future component has to
  sit inside, including ones rendered in isolation.
- `document.title` and `<html lang>` move with the switch. A panel that says
  "English" while its own tab title is still Chinese is not switched.

## 2. Architecture: who is allowed to do what

| Layer | May do | May **not** do |
|---|---|---|
| side panel (React) | read/write `chrome.storage.local`, send messages, render, read a PDF the user chose | make network calls, touch the page |
| service worker | talk to `127.0.0.1`, assemble the request payload from storage, forward messages | touch the page, hold profile data across events |
| content script | scan controls, write approved values, click a radio/checkbox | make network calls, read storage, submit |

Three consequences, each deliberate:

1. **The page can never reach the backend.** A content script runs in a page's
   origin; giving it network access would mean any page the user visits could
   read their profile out of the local server.
2. **The service worker is the sole network owner**, and it assembles the payload
   from `chrome.storage.local` rather than from the panel's message. A
   compromised or buggy panel cannot widen what is sent, and the worker re-reads
   storage on every event because a service worker is torn down between events.
3. **The panel never sees a fill it did not ask for.** Filling goes
   panel → worker → content script as a separate, user-initiated message.

## 3. The four authorisable modules

`personal_info`, `internship`, `projects`, `education` — each has its own
checkbox, and each is independent.

- Unticking a module removes it from the payload **before** it is sent
  (`storage.profileForRequest`), and the worker re-checks.
- The server strips it again if the client sends it anyway, and reports what it
  removed in `privacy.dropped_modules`. The panel shows that list, so the user can
  see the guarantee held rather than take it on trust.
- `storage.stripForbidden` removes document numbers from the profile before it is
  persisted to `chrome.storage.local`. The assistant never asks for them, so this
  should be a no-op — it is there so that "should be" is not the only defence.

There is **one** profile slot, whichever way it was filled. A resume upload does not
create a second one: `POST /extract_resume` returns a `UserProfile`, and the panel
writes it into the same place the manual form writes to, so a profile corrected by
hand and a profile read out of a PDF can never drift apart. Applying an upload is a
separate click — an upload that silently replaced a hand-typed profile would be
destructive and, worse, quiet about it.

`App.tsx`'s `profileSource` (`manual` | `uploaded`) is what records which of the two
happened. It is deliberately **session-only**: persisting it would mean a schema
change to `rjd_state_v1` for a label the user reads once, and a stored "uploaded"
that outlived the user retyping every field would be a lie rather than a memory.

## 4. What the panel does, in order

1. **Authorise** — tick the modules you are willing to send.
2. **Profile** — type it in, or upload a PDF resume and apply what comes back (see
   section 8). Either way nothing is uploaded: a resume is read in the browser.
3. **Scan** — asks the content script for the page's controls, sends them to
   `/scan`, shows what was found, what will be skipped and why.
4. **Job posting** — paste the text, or a URL for `/jd/fetch` to read. Then
   `/jd/analyze` shows the requirements and, more usefully, what the posting asks
   for that your profile does not evidence.
5. **Generate** — `/generate` returns one row per control.
6. **Review** — every row is editable. Edit-wins is enforced on both sides: the
   client keeps an edited-row draft map, and the server refuses to overwrite a
   field that already holds a value unless the user explicitly clicks regenerate
   (`overwrite_filled`).
7. **Fill** — "Fill confirmed rows" writes only rows the user has individually
   ticked. There is no "fill everything" path.

## 5. Never submitting

This is the invariant the whole extension is built around, and it is enforced in
four independent places:

- `manifest.json` requests **no** `webRequest`, no `declarativeNetRequest` and no
  scripting permission beyond the declared content script.
- The content script contains **no** `form.submit()`, no `requestSubmit()` and no
  `SubmitEvent`. Its only `.click()` is guarded to `radio` / `checkbox`.
- `writeOne` refuses any element whose tag is a button or whose type is
  `submit`/`reset`/`image`/`button`/`file`/`password`.
- The backend exposes no write endpoint at all, so there is nothing to call even
  if the extension wanted to.

`scripts/e2e_check.py` asserts the first three statically on the built bundle and
the fourth against the live OpenAPI schema.

## 6. The content script

### Field identity

`computeFieldId` mirrors `server/field_map.compute_field_id`: `wf_` + the first 12
hex of `sha1(name|id|label|placeholder)`, or `wf_anon_NNN` when a control has
none of those. Both sides must agree, because the panel stores the user's edits
against these ids — an id that changed between a scan and a fill would silently
discard the user's typing. The server adopts the id the content script sends.

`crypto.subtle` is unavailable on insecure origins, which is exactly where a real
application form tends to live, so there is a deterministic non-crypto fallback.
Ids only need to be stable and collision-free within one page; a weaker hash is
strictly better than failing to scan.

### Writing values

React and Vue install a value tracker on inputs. Assigning `element.value`
directly updates the DOM but leaves the framework's state stale, so the next
keystroke or validation pass wipes it. `setNativeValue` goes through the
prototype's own setter, then `input` / `change` / `blur` are dispatched so the
page's own handlers run. After writing, the value is read back; if the page
cleared it, the row is reported as needing a manual paste rather than as filled.

A write that survives that read-back also **marks the control** for ~600ms: the
`rjd-highlight` class, backed by a `<style>` element the content script injects
once. On a form with forty controls, the panel saying "filled" is not the same as
knowing *which* box changed. It is a class rather than an inline style, so the
page's own CSS keeps winning; and an outline rather than a restyle, so nothing about
the page's appearance changes beyond a green ring that fades. The panel's matching
row flash (`.row-just-filled`, 800ms, plus a tick that fades over 2s) is the same
signal on the other side of the loopback, keyed on the fill *result object* so that
a re-render which filled nothing cannot re-trigger it. Both are disabled under
`prefers-reduced-motion`.

### Labels

A field is labelled from, in order: `label[for]`, `aria-label`,
`aria-labelledby`, a wrapping `<label>` (with the control's own text removed so a
`<select>`'s options do not become its name), then nearby text. The nearby-text
step accepts only a **leaf** element — an element with no element children. Taking
any previous sibling wholesale made the preceding `<section>` into the submit
button's name, which came out as "Attachments Upload CV Set a password for your
applicant portal": three unrelated controls stitched together.

A `<fieldset><legend>` is deliberately **not** used as help text. It describes the
section, not the field, and the server classifies a field by its label plus its
help text — so a section heading leaked into every field inside it. The concrete
failure: a field labelled "Why do you want this role?" inside a section called
"Skills and motivation" matched the skills pattern, was classified as a skills
field, and the assistant proposed the candidate's skill list as the answer to a
free-text motivation question. The label rule above is the same mistake found a
second time, in `label` rather than `help_text`.

### What is never read

`password` and `file` controls are reported — the panel has to be able to say why
it leaves them alone — but their **value is never read**. A password is a secret
and a file input holds a browser-managed fake path; neither is ever filled, so
reading them would move a secret across the loopback HTTP boundary for no benefit
at all. The server refuses both anyway and blanks the value on the way back.

This was measured, not assumed: before the rule existed, a password typed into the
demo page came back as `current_value` in the scan result. `browser_check.mjs`
asserts it in section 6, and `scripts/e2e_check.py` asserts the mirrored rule in
its Python approximation.

## 7. What is verified, and what is not

**Verified:**

- `npm run typecheck` -> clean (`tsc --noEmit`, strict).
- `npm run build` -> clean; `dist/` contains `manifest.json`, `panel.html`,
  `background.js`, `content.js` and the hashed panel assets.
- `dist/content.js` contains no `import`/`export`, no `.submit(`, no
  `requestSubmit`, and no `legend` lookup.
- **In a real browser** - `node extension/scripts/browser_check.mjs` -> **44/44**,
  loaded unpacked into Edge 153 and driven over CDP. The whole round — backend,
  demo pages and browser — is started and torn down by one command,
  `bash extension/scripts/_run_browser_check.sh`, because this machine reclaims
  background jobs the moment the call that started them returns. That driver
  refuses to start while anything already holds 8765/8770/9222: a second backend
  that fails to bind leaves the *old* one answering `/health`, and every check then
  passes against a stale build — which is exactly how a missing route once
  presented itself as a frontend bug. Details below.
- `dist/pdf.worker.js` is byte-identical to
  `node_modules/pdfjs-dist/build/pdf.worker.min.mjs`, and is still an ES module —
  which PDF.js v6 requires, because it constructs the worker with
  `{ type: "module" }`.
- `scripts/ui_headless_check.py` -> 16/16 (that is the Streamlit UI, not this one).

### 7.1 The browser round (`scripts/browser_check.mjs`)

This is the check that moves the content script from *built* to *verified*. It
needs a browser that already has the extension loaded and a debug port open:

```
python -m server.app --port 8765
python -m http.server 8770 --bind 127.0.0.1 --directory demo

# Chrome refuses --load-extension on branded builds from 137 onwards; Edge honours
# it. A throwaway --user-data-dir is required either way: an existing profile
# ignores the flag, and remote debugging is refused on the default profile.
msedge.exe --user-data-dir=<throwaway> \
           --load-extension=<abs path>/extension/dist \
           --disable-extensions-except=<abs path>/extension/dist \
           --remote-debugging-port=9222 --no-first-run \
           --new-window http://127.0.0.1:8770/application_form.html

node extension/scripts/browser_check.mjs
```

Nothing to install: Node 22's built-in `WebSocket` and `fetch` are the whole
client. The token is read from `artifacts/server_token.txt` unless `RJD_TOKEN` is
set; options are `--port=`, `--backend=`, `--demo=`, `--extension-id=`.

What it establishes:

| Check | Evidence |
|---|---|
| the MV3 worker starts | a `service_worker` target for this extension appears, once woken |
| the content script is injected | an isolated world named after this extension exists in the page |
| a page-origin message is refused | the worker's sender guard returns no payload |
| **the two sides agree on field ids** | all 29 scanned ids equal the ids the server computes from the same fields |
| writing reaches the DOM | name, `select` and skills box all hold the intended values in the live page |
| an impossible value is refused | `Doctorate` is rejected and the previous `MSc` survives |
| a secret is never read | a password typed on the page is reported, but its value is not |
| the page never submits | the submit control is untouched and `#status` stays empty |
| the panel page renders and reflows | `panel-root` fills 305px at a 320px panel and 505px at 520px, and never scrolls sideways |
| the language switch works | EN mode has no CJK in its text or attributes; ZH mode renders Chinese with no `(...)` half |
| the resume drop zone exists | a `display: none` input with `accept="application/pdf,.pdf"` inside the drop zone |
| extracted text reaches the backend | `RJD_EXTRACT_RESUME` -> `/extract_resume` returns a profile with an email and an uncertain-field list |
| a write is marked on the page | the filled control carries `rjd-highlight`, from an injected stylesheet |

Three mechanisms are worth knowing before debugging this script, because all three
were discovered by it failing first:

- `chrome.runtime.sendMessage` from a service worker does **not** reach its own
  `onMessage` ("receiving end does not exist"), and `import()` is disallowed on a
  `ServiceWorkerGlobalScope`. The check therefore sends requests downward with
  `chrome.tabs.sendMessage`, which is what `background.ts` does itself.
- An MV3 worker is evicted when idle, so it may legitimately be missing from the
  target list. A message from the content script's isolated world wakes it - which
  is also how the sender guard gets exercised.
- **The sender guard had to change because of this script.** It used to read "the
  sender has a `tab`" as "the sender is a content script", and refuse those. But the
  panel page opened as an ordinary tab *also* has a `tab`, so the guard silently cut
  the panel off from the backend: every request came back `undefined`, with no error
  anywhere. It now compares the sender's URL against the extension's own origin,
  which is the property that actually separates a content script from a panel page.

### 7.2 Still not verified

- **The side panel *container* has never opened.** `chrome.sidePanel.open()` refuses
  a synthesised gesture and follows a real click on the toolbar icon only, so no
  script can open it. This is a much smaller gap than it was, because
  `browser_check.mjs` now renders the panel **page** — `chrome-extension://<id>/panel.html`
  opened as an ordinary tab — and drives it in sections 8–11. That is the same React
  build, the same `chrome.storage.local` and the same service worker, so the panel's
  own rendering, its storage round-trip and the panel-to-worker leg of the message
  protocol **are** exercised. What remains unexercised is narrowly the side-panel
  *hosting*: that Chrome puts the page in the side panel rather than a tab, and that
  the panel then sizes itself to a resizable column.
- **No real PDF has been put through PDF.js by a person.** The browser check proves
  the drop zone renders and that text reaches `/extract_resume`, but it never hands a
  PDF to the file input; the parsing step itself is covered only by the manual pass
  (section 7.4).
- **React-safe writing against a real React form** is unverified. `setNativeValue`
  is the documented technique and it is confirmed against a plain form, but the
  demo page is not a React app.
- **A live model run driven by the panel** has not happened. The live model was
  exercised through the backend over HTTP - see root `README.md` section 12.5 -
  not through this panel.
- **`scripts/e2e_check.py` re-implements the DOM extraction in Python.** It
  validates the *server* contract against a realistic page, not this content
  script; the browser check above is what covers the content script.

### 7.3 How to close it - one click

Load `extension/dist` unpacked, open `demo/application_form.html`, click the
toolbar icon, paste the token from `artifacts/server_token.txt` into the panel's
settings, then Scan -> Generate -> Apply on one row. That single pass answers the
last remaining question — whether a real toolbar click opens the side-panel
container — and re-checks by hand what the script now covers automatically: that
`chrome.storage.local` survives a reload, that a confirmed value reaches the input,
and that the submit button is left alone.

### 7.4 The manual pass, step by step

**Why this section exists.** Section 7.2 records a gap, and a gap with no procedure
behind it never closes. `chrome.sidePanel.open()` refuses a synthesised gesture, so
no script can open the side panel *container*. After `browser_check.mjs` renders and
drives the panel page (sections 8–11), what is left is narrow — and this pass is
what closes it:

| surface | covered by |
|---|---|
| the content script in a real page (scan, write, refuse, never submit) | `extension/scripts/browser_check.mjs` (37/37, real browser) |
| the server contract (scan / generate / guards / counts) | `scripts/run_form_matrix.py`, and `scripts/e2e_check.py` |
| **the side panel *container*: that a real toolbar click opens it, and that it sizes to a resizable column** | **this section only - a person has to click.** The panel page itself is driven by `browser_check.mjs` sections 8–11 |
| **a real PDF through PDF.js** | **this section only - a person has to choose a file** (the drop zone and the `/extract_resume` leg are scripted) |

The script `scripts/run_form_matrix.py` drives the *server* against the same
forms with a Python re-implementation of the DOM extraction. It is not a
substitute for this pass and its report says so: it cannot open a panel, cannot
write to `chrome.storage.local`, and cannot see whether React renders.

The full checklist, with the boxes to tick, lives at
[`../scripts/manual_panel_check.md`](../scripts/manual_panel_check.md). It is
about ten minutes for the first pass. The short form:

**Preconditions**

```bash
cd /path/to/resume_jd_matcher

python -m server.app --port 8765                     # backend, loopback, token
python -m http.server 8770 --bind 127.0.0.1 --directory demo
```

Two traps, both measured, both silent:

- **`file://` will not work.** `dist/manifest.json` matches `http://*/*` and
  `https://*/*` only. A page opened from disk looks like a broken extension
  rather than a wrong URL. Use the `http.server` above.
- **Never launch a browser with `--load-extension` and trust the exit code.**
  On a branded Chrome build (tested on 153) the flag is accepted and silently
  ignored - only the browser's three built-in component extensions load. Load
  unpacked through the extensions UI, or verify the load by reading
  `Default/Secure Preferences` -> `extensions.settings` and confirming the entry
  has `location: 8` and an empty `disable_reasons`. Edge honours the flag.

**Steps**

1. Open `edge://extensions` (or `chrome://extensions`), enable Developer mode,
   **Load unpacked** -> select `extension/dist`. The card must show version
   `0.3.0` and no red Errors button.
2. Open `http://127.0.0.1:8770/form_matrix/form_01_baseline.html`.
3. **Click the toolbar icon once.** This real click is what `sidePanel.open()`
   demands; there is no programmatic route.
4. Paste the token from `artifacts/server_token.txt` into the panel settings,
   then **Scan**, then **Generate**.
5. Read the rows against the two hard rules: *Passport number* and
   *NRIC / national ID number* carry **no value** and offer no Apply;
   *Full name* on `form_05_traps.html` arrives pre-filled and must **not** be
   overwritten.
6. Pick one ordinary row and **Apply**. The value must land in the control on
   the page. Note separately what happens on the **readonly** control (*Email
   address (locked)*, form_05) - programmatic writes are not blocked by
   `readonly` in the DOM, but this has never been verified in a browser.
7. **Do not press submit or reset.** Then check `window.__submitAttempts` in the
   page console: it must still be `0`.
8. In the service worker console, run
   `chrome.storage.local.get(null).then(console.log)` and confirm it holds
   settings and per-field decisions but **no plaintext resume or posting text**.
   `run_form_matrix.py` cannot read this store; this box is the only coverage.
9. Confirm `artifacts/agent_actions.jsonl` was **not** created (`RJD_SERVER_LOG`
   must have stayed unset).
10. Repeat step 5 for `form_02` .. `form_06` using the per-form table in the
    checklist. Those are the shapes the matrix covers on the server side; the
    page-side behaviour is only covered here.

**Result table**

Fill it in the checklist, not here, so the answer lives next to the steps:

| # | check | expected |
|---:|---|---|
| 1 | extension loads unpacked, no errors | version `0.3.0`, no Errors button |
| 2 | side panel opens from a real toolbar click | panel renders, not an error page |
| 3 | Scan completes | non-zero control count |
| 4 | Generate completes | every row carries a value or a reason |
| 5 | identity rows carry no value | no Apply offered |
| 6 | pre-filled row is not overwritten | `Existing Applicant` survives |
| 7 | applying a value writes it into the page | the control holds it |
| 8 | `window.__submitAttempts === 0` after applying | page never submitted |
| 9 | `chrome.storage.local` holds no resume or posting text | settings + decisions only |
| 10 | `artifacts/agent_actions.jsonl` was not created | file absent |
| 11 | the five other forms behave as the table describes | as listed |

## 8. Resume upload

A PDF resume can fill the profile instead of typing it in. What matters is where the
file goes: **nowhere.**

```
choose or drop a PDF
  -> pdf.ts              PDF.js reads it in the panel page; the file stays in the browser
  -> extracted text      the only thing that crosses the loopback boundary
  -> RJD_EXTRACT_RESUME  panel -> service worker (the worker owns the network)
  -> api.ts              POST /extract_resume
  -> server              reuses src/rules/fields.extract_fields + field_map.render_profile
  -> UserProfile         shown for review; written only on "Use this profile"
```

- **The PDF is never uploaded.** Only text crosses the boundary, so the backend needs
  no file-upload surface at all — which is what lets it stay stateless without an
  exception carved out for uploads (the H3 constraint the rest of the assistant keeps).
- **The worker is shipped, not fetched.** `vite.config.ts` copies
  `pdf.worker.min.mjs` to `dist/pdf.worker.js` and `pdf.ts` registers it by extension
  URL; because that URL is same-origin with the panel, PDF.js loads the module
  directly rather than through the blob wrapper it uses for cross-origin workers. No
  CDN is involved, so reading a CV needs no network at all.
- **Applying is a separate click.** The response is shown first — which fields were
  read, and which are worth checking (`uncertain_fields`: anything the extractor
  guessed, or could not find at all) — and nothing is written to the profile until the
  user asks. An upload cannot silently replace a profile someone typed in.
- **What it will not do.** The literal extractor reads personal details and education
  only. Work history and projects come back empty however much the resume says about
  them, and the server says so in `notes` rather than implying the resume was silent.
- **Bounds.** Files over 8 MB are refused before parsing, and a PDF with no text layer
  (a scan) is reported as such rather than as an empty profile.

Verified by `browser_check.mjs` section 10 (the drop zone renders, with a hidden,
PDF-only input) and section 11 (text reaches `/extract_resume` and comes back as a
profile). Not verified: a real PDF chosen by a person — see section 7.4.

Anything that fails is recorded with the matrix's own attribution vocabulary -
`bug`, `generation wobble`, or `edge` - so the panel's failures and the server's
failures can be read side by side.
