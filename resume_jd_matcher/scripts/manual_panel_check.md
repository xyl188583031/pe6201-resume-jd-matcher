# Manual side-panel check

**Why this file exists.** The manager-side panel is the one part of the browser
assistant that cannot be automated. `chrome.sidePanel.open()` rejects a synthetic
gesture, so no script - including `extension/scripts/browser_check.mjs`, which drives
everything else over the DevTools Protocol - can open it. That measurement is recorded
in `extension/README.md` section 7 and in the root `README.md` section 12.5.

So panel rendering, the `chrome.storage.local` round trip and the one segment of the
message protocol between the panel and the service worker have **no automated
coverage**. `scripts/run_form_matrix.py` drives the server contract instead, and says so
in its report. Until the boxes below are ticked by a person, that surface is untested.

Budget: about ten minutes for the first pass, less thereafter.

---

## 0. Preconditions

Serve the forms over HTTP. The extension's content script matches
`http://*/*` and `https://*/*` only - **`file://` will not work**, and a page opened from
disk will look like a broken extension rather than a wrong URL.

```bash
cd /path/to/resume_jd_matcher

# 1. backend, loopback only, token required
python -m server.app --port 8765
#    prints the token and writes it to artifacts/server_token.txt

# 2. the simulated forms, bound to loopback
python -m http.server 8770 --bind 127.0.0.1 --directory demo
#    -> http://127.0.0.1:8770/form_matrix/form_01_baseline.html
```

- [ ] `curl -s http://127.0.0.1:8765/health` answers, and the `mode` it reports is the one
      you expect (`live_api` with a key configured, `offline_stub` without).
- [ ] `http://127.0.0.1:8770/form_matrix/form_01_baseline.html` renders, and the banner
      says **Prototype - not for live sites**.
- [ ] `artifacts/server_token.txt` exists. Copy the token; you will paste it in step 3.
      Do not paste it into anything else.

## 1. Load the extension

1. Open `edge://extensions` (or `chrome://extensions`).
2. Turn on **Developer mode**.
3. **Load unpacked** -> select `extension/dist`.

- [ ] The card lists the extension as enabled and shows version `0.3.0`.
- [ ] No red "Errors" button on the card. If there is one, stop: click it and read the
      first error before continuing.

> Known environment trap, carried over from the automated round: launching a browser with
> `--load-extension` does NOT load anything on a branded Chrome build (tested on 153) -
> the flag is accepted and silently ignored. Loading unpacked through the UI, as above, is
> not affected. If you are scripting this, verify the load by reading
> `Default/Secure Preferences` -> `extensions.settings` and checking the entry has
> `location: 8` and an empty `disable_reasons`, rather than trusting the exit code.

## 2. Open the page and the panel

1. Go to `http://127.0.0.1:8770/form_matrix/form_01_baseline.html`.
2. **Click the toolbar icon once.** This real click is the whole point: it is what
   `sidePanel.open()` requires.

- [ ] The side panel opens and shows the assistant's own UI, not an error page.
- [ ] Settings show the backend URL (`http://127.0.0.1:8765`) and a token box.

## 3. Scan, generate, review

1. Paste the token from `artifacts/server_token.txt`.
2. Press **Scan**.
3. Press **Generate**.

- [ ] **Scan** completes without an error banner.
- [ ] The panel reports a non-zero number of controls found.
- [ ] **Generate** completes; every row shows either a drafted value or a reason.
- [ ] Every row with a value offers a per-field **confirm/apply** action. Nothing is
      written into the page before you press it.
- [ ] The panel states that nothing is submitted automatically.

Now the two hard rules, which are the reason this section exists:

- [ ] **Identity documents.** The rows for *Passport number* and *NRIC / national ID
      number* show no value, and say the field is extremely sensitive and must be typed
      by the user. Apply is not offered for them.
- [ ] **Already-filled field.** *Full name* on `form_05_traps.html` arrives pre-filled
      with `Existing Applicant`. The panel must show it as already filled and must not
      overwrite it, unless you press regenerate on that row.

Then apply a couple of values and watch the page:

- [ ] Applying a value writes it into the control on the page.
- [ ] Applying a value to the **readonly** control (*Email address (locked)*, form_05)
      either succeeds or is refused with a clear message. Record which. Programmatic
      writes are not blocked by `readonly` in the DOM, but this has never been verified
      in a browser, and `run_form_matrix.py` can only reason about it.
- [ ] **Do not press the submit button.** After you have applied values, check
      `window.__submitAttempts` in the page console: it must still be `0`. If you do
      press submit (or Reset), the page blocks it and the counter increments - that is
      the page working as designed, not the assistant misbehaving.

## 4. What must never be readable afterwards

- [ ] Open the extension's service worker console (extension card -> **service worker**
      link) and run:

      ```js
      chrome.storage.local.get(null).then(console.log)
      ```

      Check the result yourself: it may hold settings and your per-field decisions, and
      it must **not** hold plaintext resume or posting text. `run_form_matrix.py`
      cannot read this store, which is why it is a manual box.

- [ ] Confirm no JSONL action log appeared: `RJD_SERVER_LOG` must have stayed unset, so
      `artifacts/agent_actions.jsonl` should not exist after your run.

## 5. The other five forms

Repeat step 3 for each. These are the shapes `run_form_matrix.py` covers on the server
side; the page-side behaviour is only covered here.

| form | what to look at | box |
|---|---|---|
| `form_01_baseline.html` | the reference shape | - [ ] matches the reference |
| `form_02_naming.html` | three identity spellings: `passportNumber`, `passport_no`, `nricNumber`; plus an `aria-label`-only field, a sibling-`<span>`-only field, and one with no visible name at all | - [ ] all three identity rows refused; - [ ] all three name-resolution shapes produce a sensible label |
| `form_03_help_text.html` | all guidance is in `<legend>`; two fields named only by their legend | - [ ] `extra_1` is reported as unnameable rather than answered; - [ ] the *Employer details* group's `Name` field is **not** filled with your own name |
| `form_04_maxlength.html` | limits of 50 / 300 / 1000 | - [ ] a value is never longer than its control's limit; - [ ] a shortened value says it was shortened |
| `form_05_traps.html` | password, submit, file, hidden CSRF, pre-filled value, a `readonly` email, a `disabled` email, a `<button type=submit>` | - [ ] the password, file, submit, reset and hidden controls get no value; - [ ] `email_readonly` gets no value and is reported as a control the page locked; - [ ] `email_disabled` gets no value and is reported as a control the page switched off; - [ ] the `<button>` does not appear in the list at all (the scanner matches `input` only) |
| `form_06_bilingual.html` | bilingual labels, two Chinese-only labels, one `contenteditable` | - [ ] `huzhao`, whose label is Chinese only, is refused as an identity document; - [ ] `beizhu`, whose label is Chinese only, is reported as unnameable; - [ ] the `contenteditable` question is accepted |

## 6. Record the result

| # | check | result | note |
|---:|---|---|---|
| 1 | extension loads unpacked with no errors | | |
| 2 | side panel opens from a real toolbar click | | |
| 3 | Scan completes | | |
| 4 | Generate completes | | |
| 5 | identity rows carry no value | | |
| 6 | pre-filled row is not overwritten | | |
| 7 | applying a value writes it into the page | | |
| 8 | `window.__submitAttempts === 0` after applying | | |
| 9 | `chrome.storage.local` holds no resume or posting text | | |
| 10 | `artifacts/agent_actions.jsonl` was not created | | |
| 11 | the five other forms behave as the table in section 5 describes | | |

Anything that fails goes into the report's "known failures" section with the same
attribution vocabulary the matrix uses: `bug`, `generation wobble`, or `edge`.
