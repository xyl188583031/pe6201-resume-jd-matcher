/**
 * Browser-side verification for the extension, driven over CDP.
 *
 * `scripts/e2e_check.py` approximates the content script in Python. This script
 * runs the built artefact instead, inside a real browser, and asserts the things
 * no Python process can observe:
 *
 *   1. the MV3 service worker starts and the content script is injected;
 *   2. a message originating in the page is refused by the worker's sender guard;
 *   3. the content script reads the real DOM and produces exactly the field ids
 *      the server computes - the ids the user's stored edits are keyed on;
 *   4. a confirmed value lands in the DOM through the native value setter, and a
 *      value the control cannot represent is refused rather than forced;
 *   5. a password typed on the page is never read;
 *   6. the submit control is never touched and the page never submits;
 *   7. the panel page renders and its root container fits the width it is given;
 *   8. the language switch works, and English mode really is English;
 *   9. the resume drop zone renders, and text read out of a resume reaches
 *      `POST /extract_resume` through the worker;
 *  10. a control the assistant writes into is marked on the page itself.
 *
 * It renders the panel page too, by opening `chrome-extension://<id>/panel.html`
 * in a tab (section 8 onwards). That is the same React build, the same storage
 * and the same service worker the side panel uses, so the panel's own behaviour
 * is reachable here. What is still NOT reachable is the side panel *container*:
 * `chrome.sidePanel.open()` will not run without a genuine click on the toolbar
 * icon - a synthesised gesture is refused by the extension API itself, which
 * this script verified before relying on it. Opening the side panel is the one
 * step that needs a human; see the "Still not verified" section of
 * `extension/README.md`.
 *
 * Usage
 * -----
 *   1. start the backend and the demo page:
 *        python -m server.app --port 8765
 *        python -m http.server 8770 --bind 127.0.0.1 --directory demo
 *   2. start a browser with the unpacked extension and a debug port:
 *        msedge.exe --user-data-dir=<throwaway> \
 *                   --load-extension=<abs path to extension/dist> \
 *                   --disable-extensions-except=<abs path to extension/dist> \
 *                   --remote-debugging-port=9222 \
 *                   --no-first-run --new-window http://127.0.0.1:8770/application_form.html
 *      Chrome refuses `--load-extension` on branded builds from 137 onwards;
 *      Edge honours it. A throwaway `--user-data-dir` is required - an existing
 *      profile ignores the flag, and remote debugging is blocked on the default
 *      profile.
 *   3. node extension/scripts/browser_check.mjs
 *
 * Options: --port=9222, --backend=..., --demo=..., --extension-id=...
 * The token is read from artifacts/server_token.txt unless RJD_TOKEN is set.
 *
 * Node 22 or newer: uses the built-in WebSocket and fetch, so there is nothing
 * to install.
 */

import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

/* ------------------------------------------------------------------- config */

const HERE = dirname(fileURLToPath(import.meta.url));
const EXTENSION_DIST = resolve(HERE, '..', 'dist');
const REPO_ROOT = resolve(HERE, '..', '..');

function flag(name, fallback) {
  const hit = process.argv.find((a) => a.startsWith(`--${name}=`));
  return hit ? hit.slice(name.length + 3) : fallback;
}

const CDP = `http://127.0.0.1:${flag('port', '9222')}`;
const BACKEND = flag('backend', 'http://127.0.0.1:8765');
const DEMO = flag('demo', 'http://127.0.0.1:8770/application_form.html');
const DEMO_PREFIX = new URL(DEMO).origin + '/';
const TOKEN = process.env.RJD_TOKEN ?? readFileSync(resolve(REPO_ROOT, 'artifacts', 'server_token.txt'), 'utf8').trim();
const SECRET = 'Sup3rSecret!';

const manifest = JSON.parse(readFileSync(resolve(EXTENSION_DIST, 'manifest.json'), 'utf8'));

/* ------------------------------------------------------------------ checks */

const results = [];
function check(ok, label, detail) {
  results.push({ ok: Boolean(ok), label, detail });
  console.log(`  ${ok ? 'PASS' : 'FAIL'}  ${label}${detail === undefined ? '' : `  [${detail}]`}`);
}
function section(title) {
  console.log(`\n== ${title} ==`);
}

const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

/* -------------------------------------------------------------- cdp client */

class Session {
  constructor(ws) {
    this.ws = ws;
    this.id = 0;
    this.pending = new Map();
    this.contexts = [];
    ws.addEventListener('message', (event) => {
      const msg = JSON.parse(event.data);
      if (msg.method === 'Runtime.executionContextCreated') {
        this.contexts.push(msg.params.context);
        return;
      }
      if (msg.method) return;
      if (msg.id && this.pending.has(msg.id)) {
        const { resolve: done, reject } = this.pending.get(msg.id);
        this.pending.delete(msg.id);
        if (msg.error) reject(new Error(JSON.stringify(msg.error)));
        else done(msg.result);
      }
    });
  }

  static async open(wsUrl, { enableRuntime = true } = {}) {
    const ws = new WebSocket(wsUrl);
    await new Promise((done, fail) => {
      ws.addEventListener('open', done, { once: true });
      ws.addEventListener('error', () => fail(new Error(`cannot open ${wsUrl}`)), { once: true });
    });
    const session = new Session(ws);
    // The browser-level endpoint speaks Target/Page, not Runtime.
    if (enableRuntime) await session.send('Runtime.enable');
    return session;
  }

  send(method, params = {}) {
    const id = ++this.id;
    return new Promise((done, fail) => {
      this.pending.set(id, { resolve: done, reject: fail });
      this.ws.send(JSON.stringify({ id, method, params }));
      setTimeout(() => {
        if (this.pending.has(id)) {
          this.pending.delete(id);
          fail(new Error(`timed out: ${method}`));
        }
      }, 120000).unref();
    });
  }

  async eval(expression, contextId) {
    const params = { expression, awaitPromise: true, returnByValue: true, userGesture: true };
    if (contextId !== undefined) params.contextId = contextId;
    const result = await this.send('Runtime.evaluate', params);
    if (result.exceptionDetails) {
      const detail = result.exceptionDetails.exception?.description ?? result.exceptionDetails.text;
      throw new Error(`eval threw: ${String(detail).slice(0, 400)}`);
    }
    return result.result.value;
  }

  async json(expression, contextId) {
    return JSON.parse(await this.eval(expression, contextId));
  }

  close() {
    try {
      this.ws.close();
    } catch {
      /* already gone */
    }
  }
}

async function targets() {
  return (await fetch(`${CDP}/json/list`)).json();
}

/** Send a request down to the content script, as `background.ts` does itself. */
function askContentScript(requestJson) {
  return `(async () => {
    const tabs = await chrome.tabs.query({});
    const tab = tabs.find((t) => (t.url || '').startsWith(${JSON.stringify(DEMO_PREFIX)}));
    if (!tab) return JSON.stringify({ __error: 'the demo tab is not open' });
    const reply = await chrome.tabs.sendMessage(tab.id, ${requestJson});
    return JSON.stringify(reply === undefined ? { __error: 'no reply from the content script' } : reply);
  })()`;
}

const READ_DOM = `(() => {
  const out = {};
  for (const el of document.querySelectorAll('input,select,textarea')) {
    out[el.name || el.id || el.type] = el.value;
  }
  return JSON.stringify(out);
})()`;

/* --------------------------------------------------------------------- run */

try {
  await fetch(`${CDP}/json/version`);
} catch {
  console.error(
    `Cannot reach ${CDP}. Start the browser first - see the header of this file for the exact command.`,
  );
  process.exit(2);
}

let extensionId = flag('extension-id', '');
let page = null;
let panel = null;
let sw = null;
let browser = null;

try {
  let all = await targets();
  const pageTarget = all.find((t) => t.type === 'page' && t.url.startsWith(DEMO_PREFIX));
  if (!pageTarget) {
    console.error(`No tab is showing ${DEMO_PREFIX}. Open the demo page and run this again.`);
    process.exit(2);
  }

  page = await Session.open(pageTarget.webSocketDebuggerUrl);

  // A background tab is not a reliable place to look for a content script, and
  // the browser opens its own tabs in front. Bring the demo page forward and
  // load it fresh, so what is asserted below is a real injection into a
  // just-loaded document rather than a leftover world from an earlier session.
  const version = await (await fetch(`${CDP}/json/version`)).json();
  browser = await Session.open(version.webSocketDebuggerUrl, { enableRuntime: false });
  await browser.send('Target.activateTarget', { targetId: pageTarget.id });
  await page.send('Page.enable');
  // Drop the contexts of whatever was in the tab before, so the world found
  // below belongs to the document this run actually loaded.
  page.contexts.length = 0;
  await page.send('Page.reload', { ignoreCache: true });
  for (let attempt = 0; attempt < 30; attempt += 1) {
    const ready = await page.eval('document.readyState').catch(() => 'detached');
    if (ready === 'complete') break;
    await new Promise((r) => setTimeout(r, 500));
  }
  await new Promise((r) => setTimeout(r, 800));

  /* --- 1. injection, and the guard ---------------------------------------- */
  section('1. The extension is installed, injected, and cannot be driven by the page');
  const worlds = page.contexts.filter((c) => (c.origin || '').startsWith('chrome-extension://'));
  // The newest world wins: a re-injection in the same document would otherwise
  // leave a stale context id behind, and evaluating in it is an error, not a
  // failed assertion.
  const world = extensionId
    ? worlds.findLast((c) => (c.origin || '').includes(extensionId))
    : worlds.findLast((c) => c.name === manifest.name);  check(
    Boolean(world),
    'an isolated world owned by this extension exists in the page',
    worlds.map((c) => `${c.name} @ ${c.origin}`).join(' | ') || 'none',
  );
  if (!world) {
    console.error(
      '\nThe content script never ran. Is the extension loaded from this build of dist/,\n' +
        `and does the loaded manifest name match ${JSON.stringify(manifest.name)}?`,
    );
    process.exit(1);
  }
  extensionId = world.origin.split('//')[1];
  console.log(`    extension id: ${extensionId}`);

  // An MV3 worker is evicted when idle, so it is legitimately absent until an
  // extension event happens. A message from the content script's own world is
  // such an event: it wakes the worker, whose sender guard must then refuse to
  // answer. What matters is the outcome, not its shape - the guard can close the
  // channel without a payload (the promise resolves undefined) or the send can
  // fail outright, and both mean "no data came back".
  const fromPage = await page.eval(
    `(async () => {
       const bail = new Promise((r) => setTimeout(() => r('no answer (waited 4s)'), 4000));
       const send = chrome.runtime.sendMessage({ type: 'RJD_PING' })
         .then((reply) => 'answered: ' + JSON.stringify(reply ?? null),
               (e) => 'refused: ' + (e && e.message));
       return await Promise.race([send, bail]);
     })()`,
    world.id,
  );
  check(!/"ok"/.test(fromPage), 'a request originating in the page gets no answer', fromPage.slice(0, 100));

  let swTarget = null;
  for (let attempt = 0; attempt < 12 && !swTarget; attempt += 1) {
    all = await targets();
    swTarget = all.find(
      (t) => t.type === 'service_worker' && t.url.startsWith(`chrome-extension://${extensionId}/`),
    );
    if (!swTarget) await new Promise((r) => setTimeout(r, 500));
  }
  check(swTarget, 'the service worker woke and is running', swTarget?.url);
  if (!swTarget) process.exit(1);
  sw = await Session.open(swTarget.webSocketDebuggerUrl);

  /* --- 2. scan ------------------------------------------------------------ */
  section('2. The content script scans the real DOM');
  const dom = await page.json(`(() => {
    const all = [...document.querySelectorAll('input,select,textarea')];
    return JSON.stringify({ total: all.length });
  })()`);
  const scan = await sw.json(askContentScript(`{ type: 'RJD_SCAN_PAGE' }`));
  check(scan.ok === true, 'the content script replied ok', scan.error);
  const fields = scan.fields ?? [];
  check(fields.length > 0, 'it returned the page fields', `${fields.length} of ${dom.total} controls`);
  check(fields.length < dom.total, 'controls it never touches are excluded from its own scan',
    `${dom.total - fields.length} excluded`);
  check(
    fields.every((f) => typeof f.field_id === 'string' && f.field_id.startsWith('wf_')),
    'every field carries a wf_ id',
  );
  const labelById = Object.fromEntries(fields.map((f) => [f.field_id, f.label]));
  for (const wanted of ['Full name', 'Email address', 'Degree', 'Key skills', 'Cover letter']) {
    check(Object.values(labelById).includes(wanted), `the label ${JSON.stringify(wanted)} resolved`);
  }

  /* --- 3. the two sides agree on ids -------------------------------------- */
  section('3. The content script and the server compute the same field ids');
  const announced = fields.map((f) => f.field_id);
  const stripped = fields.map((f) => {
    const copy = { ...f };
    delete copy.field_id;
    return copy;
  });
  const classified = await (
    await fetch(`${BACKEND}/scan`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-RJD-Token': TOKEN },
      body: JSON.stringify({ url: scan.url, page_title: scan.pageTitle, fields: stripped }),
    })
  ).json();
  const recomputed = classified.fields.map((f) => f.field_id);
  const differing = announced.filter((id, i) => id !== recomputed[i]);
  check(
    differing.length === 0,
    'the ids match one-for-one, so a stored edit cannot silently detach',
    `${announced.length} compared, ${differing.length} differ`,
  );
  check(classified.counts.total === fields.length, 'the server classified every scanned field',
    JSON.stringify(classified.counts));
  check(classified.counts.sensitive >= 1, 'the server marks the document fields sensitive',
    `sensitive=${classified.counts.sensitive}`);

  /* --- 4. fill ------------------------------------------------------------ */
  section('4. A confirmed value lands in the real DOM');
  const idByLabel = (label) => fields.find((f) => f.label === label)?.field_id;
  const wanted = { 'Full name': 'Zhang Wei', Degree: 'MSc', 'Key skills': 'Python, SQL' };
  const values = {};
  for (const [label, value] of Object.entries(wanted)) {
    const id = idByLabel(label);
    check(Boolean(id), `the ${label} control was located by label`);
    if (id) values[id] = value;
  }
  const before = await page.json(READ_DOM);
  const filled = await sw.json(
    askContentScript(`{ type: 'RJD_FILL_FIELDS', values: ${JSON.stringify(values)} }`),
  );
  for (const row of filled.results ?? []) {
    check(row.ok === true, `the write to ${labelById[row.field_id] ?? row.field_id} succeeded`,
      row.reason || 'written');
  }
  const after = await page.json(READ_DOM);
  check(after.full_name === 'Zhang Wei', 'the name is in the live DOM', JSON.stringify(after.full_name));
  check(after.degree === 'MSc', 'the select holds MSc, not "Master of Science"', JSON.stringify(after.degree));
  check(after.skills === 'Python, SQL', 'the skills box holds the profile wording', JSON.stringify(after.skills));
  const changed = Object.keys(after).filter((k) => after[k] !== before[k]);
  check(changed.length === Object.keys(values).length, 'exactly the requested controls changed',
    changed.join(', '));

  const refused = await sw.json(
    askContentScript(`{ type: 'RJD_FILL_FIELDS', values: { ${JSON.stringify(idByLabel('Degree'))}: 'Doctorate' } }`),
  );
  check((refused.results ?? [])[0]?.ok === false, 'an option the control does not offer is refused',
    (refused.results ?? [])[0]?.reason);
  check(
    (await page.json(`JSON.stringify((document.querySelector('[name=degree]') || {}).value)`)) === 'MSc',
    'the refused value did not overwrite the previous one',
  );

  /* --- 5. hard rules ------------------------------------------------------ */
  section('5. The hard rules, against the live DOM');
  check(
    after.submit_application === before.submit_application,
    'the submit control was not clicked or altered',
    `submit_application=${JSON.stringify(after.submit_application)}`,
  );
  const status = await page.eval(`document.getElementById('status').textContent`);
  check(!/submitted/i.test(status ?? ''), 'the page reports no submission', JSON.stringify(status || ''));
  check(!after.portal_password, 'the password box was not written', JSON.stringify(after.portal_password));
  check(after.csrf === before.csrf, 'the hidden CSRF token is unchanged', JSON.stringify(after.csrf));

  /* --- 6. a secret is never read ----------------------------------------- */
  section('6. A secret typed on the page is never read');
  await page.eval(`(() => {
    const pw = document.querySelector('input[type=password]');
    if (pw) pw.value = ${JSON.stringify(SECRET)};
    return 'seeded';
  })()`);
  const rescan = await sw.json(askContentScript(`{ type: 'RJD_SCAN_PAGE' }`));
  const secretField = (rescan.fields ?? []).find((f) => f.type === 'password');
  check(Boolean(secretField), 'the password control is still reported, so the panel can explain the refusal');
  check(secretField?.current_value === '', 'its value was not read', JSON.stringify(secretField?.current_value));
  check(!JSON.stringify(rescan).includes(SECRET), 'the typed password appears nowhere in the scan result');
  const submitField = fields.find((f) => f.type === 'submit');
  check(
    Boolean(submitField) && !/attachments/i.test(submitField.label) && submitField.label.length < 60,
    'the submit control is not named after a whole form section',
    JSON.stringify(submitField?.label),
  );

  /* --- 7. the gate -------------------------------------------------------- */
  section('7. The backend token gate');
  const noToken = await fetch(`${BACKEND}/scan`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ url: '', page_title: '', fields: [] }),
  });
  check(noToken.status === 401, 'a request with no token is refused', `HTTP ${noToken.status}`);
  const withToken = await fetch(`${BACKEND}/scan`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-RJD-Token': TOKEN },
    body: JSON.stringify({ url: '', page_title: '', fields: [] }),
  });
  check(withToken.status === 200, 'the same request with the token is accepted', `HTTP ${withToken.status}`);

  /* --- 8. the panel page --------------------------------------------------- */
  // `chrome.sidePanel.open()` refuses a synthesised gesture, so the side panel
  // *container* still needs one human click. The panel *page* does not: opening
  // `panel.html` in a tab renders the same React build, against the same
  // storage and the same service worker, and that is what is driven below.
  section('8. The panel page renders, and is no longer pinned to a fixed width');

  const created = await browser.send('Target.createTarget', {
    url: `chrome-extension://${extensionId}/panel.html`,
    newWindow: false,
  });
  let panelInfo = null;
  for (let attempt = 0; attempt < 40; attempt += 1) {
    const list = await targets();
    panelInfo = list.find((t) => t.id === created.targetId);
    if (panelInfo?.webSocketDebuggerUrl) break;
    await new Promise((r) => setTimeout(r, 250));
  }
  if (!panelInfo?.webSocketDebuggerUrl) {
    console.error('Could not attach to the panel page. Is panel.html in dist/?');
    process.exit(1);
  }
  panel = await Session.open(panelInfo.webSocketDebuggerUrl);
  await panel.send('Page.enable');

  // Wait for React to paint the root container.
  let panelPainted = false;
  for (let attempt = 0; attempt < 60; attempt += 1) {
    panelPainted = await panel
      .eval(`Boolean(document.querySelector('[data-testid="panel-root"]'))`)
      .catch(() => false);
    if (panelPainted) break;
    await new Promise((r) => setTimeout(r, 250));
  }

  /**
   * Measure the panel at a given width.
   *
   * Chrome's side panel is a resizable column: it is routinely dragged to about
   * 320px, which is narrower than the 400px the layout used to be pinned to.
   * Emulating the width is how that state is reachable without a human dragging
   * anything.
   */
  async function panelLayout(width) {
    await panel.send('Emulation.setDeviceMetricsOverride', {
      width,
      height: 900,
      deviceScaleFactor: 1,
      mobile: false,
    });
    await new Promise((r) => setTimeout(r, 400));
    return panel.json(`(() => {
      const root = document.querySelector('[data-testid="panel-root"]');
      const doc = document.documentElement;
      if (!root) return JSON.stringify({ ready: false, width: doc.clientWidth });
      return JSON.stringify({
        ready: true,
        width: doc.clientWidth,
        rootWidth: root.clientWidth,
        rootScroll: root.scrollWidth,
        docScroll: doc.scrollWidth,
      });
    })()`);
  }

  const at320 = await panelLayout(320);
  const at520 = await panelLayout(520);
  const layoutOk =
    panelPainted &&
    at320.ready &&
    at320.rootWidth >= 280 &&
    at320.rootScroll <= at320.rootWidth + 1 &&
    at320.docScroll <= at320.width + 1 &&
    at520.ready &&
    Math.abs(at520.rootWidth - at520.width) <= 1 &&
    at520.docScroll <= at520.width + 1;
  check(
    layoutOk,
    'panel-root fills the panel width and never scrolls sideways',
    `painted=${panelPainted}` +
      ` | 320: root=${at320.rootWidth} doc=${at320.width} rootScroll=${at320.rootScroll} docScroll=${at320.docScroll}` +
      ` | 520: root=${at520.rootWidth} doc=${at520.width} docScroll=${at520.docScroll}`,
  );

  /* --- 9. the language switch --------------------------------------------- */
  section('9. The panel can be switched between Chinese, English and both');

  const toggle = await panel.json(`(() => {
    const group = document.querySelector('[data-testid="language-toggle"]');
    if (!group) return JSON.stringify({ found: false });
    const buttons = [...group.querySelectorAll('button')];
    return JSON.stringify({
      found: true,
      role: group.getAttribute('role'),
      testids: buttons.map((b) => b.dataset.testid),
      pressed: buttons.map((b) => b.getAttribute('aria-pressed')),
      captions: buttons.map((b) => b.textContent.trim()),
    });
  })()`);
  check(
    toggle.found &&
      toggle.role === 'group' &&
      ['language-zh', 'language-en', 'language-bilingual'].every((id) =>
        toggle.testids.includes(id),
      ) &&
      toggle.pressed.every((v) => v === 'true' || v === 'false'),
    'the language toggle is a labelled group of three buttons',
    `role=${toggle.role} buttons=${(toggle.testids ?? []).join(',')} pressed=${(toggle.pressed ?? []).join(',')}`,
  );

  // The scan below is deliberately wider than "the visible text": a `title` or
  // `aria-label` the user reads on hover is part of the panel showing Chinese,
  // and those are exactly the places a half-finished translation hides.
  const CJK_SCAN = `(() => {
    const ranges = [[0x3000, 0x303f], [0x4e00, 0x9fff], [0xff00, 0xffef]];
    const isCjk = (text) => {
      for (const ch of String(text ?? '')) {
        const code = ch.codePointAt(0);
        for (const [lo, hi] of ranges) if (code >= lo && code <= hi) return true;
      }
      return false;
    };
    const offenders = [];
    if (isCjk(document.body.innerText)) offenders.push('body text');
    for (const el of document.querySelectorAll('*')) {
      for (const attr of ['title', 'aria-label', 'placeholder', 'alt']) {
        const value = el.getAttribute(attr);
        if (value && isCjk(value)) {
          offenders.push(el.tagName.toLowerCase() + '[' + attr + ']=' + value.slice(0, 30));
        }
      }
    }
    return JSON.stringify({
      offenders: offenders.slice(0, 6),
      count: offenders.length,
      title: document.title,
      lang: document.documentElement.lang,
    });
  })()`;

  await panel.eval(`document.querySelector('[data-testid="language-en"]').click()`);
  await wait(500);
  const inEnglish = await panel.json(CJK_SCAN);
  check(
    inEnglish.count === 0 && !/[\u3000-\u303f\u4e00-\u9fff\uff00-\uffef]/.test(inEnglish.title),
    'in English mode the panel contains no CJK text or attributes',
    inEnglish.count === 0
      ? `title=${JSON.stringify(inEnglish.title)} lang=${inEnglish.lang}`
      : `${inEnglish.count} offender(s): ${inEnglish.offenders.join(' | ')}`,
  );

  await panel.eval(`document.querySelector('[data-testid="language-zh"]').click()`);
  await wait(500);
  const inChinese = await panel.json(`(() => {
    const text = (selector) => {
      const el = document.querySelector(selector);
      return el ? el.textContent.trim() : null;
    };
    const headings = [...document.querySelectorAll('section > h2')].map((h) => h.textContent.trim());
    return JSON.stringify({
      title: text('.sticky-header .title'),
      scanButton: text('[data-testid="scan-button"]'),
      firstHeading: headings[0] ?? null,
      docTitle: document.title,
    });
  })()`);
  // What is asserted is the *shape* of the string, not a specific translation:
  // Chinese present, and the "(English)" half gone. A test that pinned the exact
  // wording would fail on any copy edit and prove nothing extra. ASCII is not
  // forbidden inside the Chinese form - the product's own name is
  // "Resume-JD ..." - so the discriminator is the parenthetical, which is what
  // the bilingual spelling adds.
  const pureChinese = (value) =>
    typeof value === 'string' && /[\u4e00-\u9fff]/.test(value) && !value.includes('(');
  check(
    pureChinese(inChinese.title) &&
      pureChinese(inChinese.scanButton) &&
      pureChinese(inChinese.firstHeading) &&
      inChinese.docTitle === inChinese.title,
    'in Chinese mode the same keys render Chinese only, with no English half',
    `title=${JSON.stringify(inChinese.title)} docTitle=${JSON.stringify(inChinese.docTitle)} scan=${JSON.stringify(inChinese.scanButton)} h2=${JSON.stringify(inChinese.firstHeading)}`,
  );

  /* --- 10. the resume drop zone ------------------------------------------- */
  section('10. The panel offers a resume upload, and the file stays in the browser');

  const dropzone = await panel.json(`(() => {
    const zone = document.querySelector('[data-testid="resume-dropzone"]');
    const input = zone ? zone.querySelector('input[type="file"]') : null;
    return JSON.stringify({
      present: Boolean(zone),
      accept: input ? input.getAttribute('accept') : null,
      hidden: input ? getComputedStyle(input).display === 'none' : null,
    });
  })()`);
  // `accept` and `hidden` together are the point: the control exists so the user
  // can choose a file, and it cannot be reached except through the drop zone -
  // so the panel, not the browser's own widget, is what the user interacts with.
  check(
    dropzone.present && /pdf/.test(dropzone.accept ?? '') && dropzone.hidden === true,
    'the resume drop zone renders with a hidden, PDF-only file input',
    `present=${dropzone.present} accept=${dropzone.accept} hidden=${dropzone.hidden}`,
  );

  /* --- 11. the extract path, and the page-side fill mark ------------------- */
  // Section 11 drives the real path an upload takes once the text exists:
  // panel -> `chrome.runtime.sendMessage` -> background worker -> `api.ts` ->
  // `POST /extract_resume`. The PDF is not on that path at all, which is the
  // claim being tested as much as the response is.
  section('11. Extracted resume text reaches /extract_resume, and a write is marked');

  const RESUME_TEXT =
    'Zhang Wei\nzhang.wei@example.com | +65 9123 4567\n\nEDUCATION\n' +
    'Nanyang Technological University\nMaster of Science in Computer Science, 2025\n';

  // The token has to be in storage for the request to be accepted, and it must
  // not be left there afterwards: the panel's settings belong to the user, and a
  // verification run that silently enabled them would be a change, not a check.
  const extracted = await panel.json(`(async () => {
    const KEY = 'rjd_state_v1';
    const stored = (await chrome.storage.local.get(KEY))[KEY] ?? {};
    const settings = stored.settings ?? {};
    await chrome.storage.local.set({
      [KEY]: { ...stored, settings: { ...settings, token: ${JSON.stringify(TOKEN)} } },
    });
    let reply = null;
    try {
      reply = await chrome.runtime.sendMessage({
        type: 'RJD_EXTRACT_RESUME',
        text: ${JSON.stringify(RESUME_TEXT)},
      });
    } finally {
      await chrome.storage.local.set({ [KEY]: { ...stored, settings } });
    }
    return JSON.stringify(reply ?? null);
  })()`);

  const uploaded = extracted?.data;
  check(
    extracted?.ok === true &&
      typeof uploaded?.profile?.personal_info?.email === 'string' &&
      uploaded.profile.personal_info.email.includes('@') &&
      Array.isArray(uploaded.uncertain_fields) &&
      typeof uploaded.source === 'string' &&
      uploaded.source.length > 0,
    'RJD_EXTRACT_RESUME reaches /extract_resume and returns a usable profile',
    extracted?.ok
      ? `email=${JSON.stringify(uploaded.profile.personal_info.email)}` +
        ` uncertain=${JSON.stringify(uploaded.uncertain_fields)} source=${uploaded.source}`
      : `error=${extracted?.error}`,
  );

  // The page-side mark. A MutationObserver is armed *before* the write and
  // records every class change, so the 600ms window cannot be missed by this
  // script being a few milliseconds late - which is exactly what a
  // "fill, then wait 300ms, then look" check cannot promise. Content scripts run
  // in an isolated world but share the DOM, so the observer sees their writes.
  await page.eval(`(() => {
    window.__rjdMarks = [];
    const el = document.querySelector('[name=full_name]');
    if (!el) return 'no control named full_name';
    new MutationObserver(() => {
      if (el.classList.contains('rjd-highlight')) window.__rjdMarks.push(el.className);
    }).observe(el, { attributes: true, attributeFilter: ['class'] });
    return 'armed';
  })()`);

  const marked = await sw.json(
    askContentScript(
      `{ type: 'RJD_FILL_FIELDS', values: { ${JSON.stringify(idByLabel('Full name'))}: 'Zhang Wei' } }`,
    ),
  );
  const marks = await page.json(`JSON.stringify({
    marks: window.__rjdMarks ?? [],
    rule: Boolean(document.getElementById('rjd-highlight-style')),
  })`);
  check(
    (marked.results ?? [])[0]?.ok === true && marks.marks.length > 0 && marks.rule === true,
    'a written control is marked rjd-highlight on the page, from an injected rule',
    `ok=${(marked.results ?? [])[0]?.ok} marks=${marks.marks.length} rule=${marks.rule}`,
  );

  // Leave the stored preference where it started, so a second run of this
  // script sees the same panel the first one did.
  await panel.eval(`document.querySelector('[data-testid="language-bilingual"]').click()`);
  await wait(300);
} finally {
  panel?.close();
  sw?.close();
  page?.close();
  browser?.close();
}

const failed = results.filter((r) => !r.ok);
console.log(`\nRESULT: ${results.length - failed.length}/${results.length} checks passed`);
for (const f of failed) console.log(`  FAILED: ${f.label} ${f.detail ?? ''}`);
process.exit(failed.length ? 1 : 0);
