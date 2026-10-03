// _print_pdf.mjs — print an HTML file to PDF with headless Edge over CDP.
//
//   node report/_print_pdf.mjs <input.html> <output.pdf>
//
// Why CDP and not `msedge --print-to-pdf`: only Page.printToPDF accepts a
// headerTemplate / footerTemplate, which is what gives the per-page A1 header
// and a real "Page N" counter. `--print-to-pdf` can only emit Chromium's own
// default furniture (or none).
import { spawn } from 'node:child_process';
import { writeFileSync, mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { pathToFileURL } from 'node:url';

const [, , htmlArg, pdfArg] = process.argv;
if (!htmlArg || !pdfArg) {
  console.error('usage: node _print_pdf.mjs <input.html> <output.pdf>');
  process.exit(2);
}

const htmlPath = resolve(htmlArg);
const pdfPath = resolve(pdfArg);
const EDGE = 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe';
const PORT = 9333;
const NEXT = 'Segoe UI, Helvetica Neue, Arial, sans-serif';
const RED = '#A6192E';

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const profile = mkdtempSync(join(tmpdir(), 'edgepdf-'));
const pageUrl = pathToFileURL(htmlPath).href;

const edge = spawn(
  EDGE,
  [
    '--headless=new',
    '--disable-gpu',
    '--no-first-run',
    '--no-default-browser-check',
    '--disable-extensions',
    '--disable-features=Translate',
    `--remote-debugging-port=${PORT}`,
    `--user-data-dir=${profile}`,
    pageUrl,
  ],
  { stdio: 'ignore' }
);

// The header underline is a border on the inner box; padding keeps it aligned
// with the 20mm content margin.
const headerTemplate = `
<div style="width:100%;box-sizing:border-box;padding:0 20mm;font-family:${NEXT};font-size:8pt;color:${RED};">
  <div style="display:flex;justify-content:space-between;padding-bottom:2px;border-bottom:1px solid ${RED};">
    <span>PE6201 \u00b7 EMERGING AI TECHNOLOGIES</span>
    <span>Graduate Resume\u2013JD Matcher</span>
  </div>
</div>`;

const footerTemplate = `
<div style="width:100%;box-sizing:border-box;padding:0 20mm;font-family:${NEXT};font-size:8pt;color:#555555;">
  <div style="display:flex;justify-content:space-between;">
    <span>Nanyang Technological University \u00b7 MSc Enterprise AI \u00b7 T1 AY2026-27</span>
    <span>Page <span class="pageNumber"></span></span>
  </div>
</div>`;

async function findPageTarget() {
  for (let i = 0; i < 100; i++) {
    try {
      const res = await fetch(`http://127.0.0.1:${PORT}/json/list`);
      const list = await res.json();
      const page = list.find((t) => t.type === 'page' && t.url.startsWith('file:'));
      if (page && page.webSocketDebuggerUrl) return page;
    } catch {
      /* browser not up yet */
    }
    await sleep(250);
  }
  throw new Error('no file:// page target appeared on CDP port ' + PORT);
}

const target = await findPageTarget();
const ws = new WebSocket(target.webSocketDebuggerUrl);
let nextId = 0;
const pending = new Map();

ws.addEventListener('message', (ev) => {
  const msg = JSON.parse(ev.data);
  if (msg.id && pending.has(msg.id)) {
    pending.get(msg.id)(msg);
    pending.delete(msg.id);
  }
});

await new Promise((ok, fail) => {
  ws.addEventListener('open', ok);
  ws.addEventListener('error', () => fail(new Error('CDP socket error')));
});

const send = (method, params = {}) =>
  new Promise((res) => {
    const id = ++nextId;
    pending.set(id, res);
    ws.send(JSON.stringify({ id, method, params }));
  });

await send('Page.enable');
await send('Runtime.enable');

// wait for the document (and its inline CSS) to be fully parsed
for (let i = 0; i < 100; i++) {
  const r = await send('Runtime.evaluate', {
    expression: 'document.readyState',
    returnByValue: true,
  });
  if (r.result?.result?.value === 'complete') break;
  await sleep(200);
}
await sleep(500); // let font fallback / layout settle

const MM = 1 / 25.4; // mm -> inch
const out = await send('Page.printToPDF', {
  printBackground: true,
  preferCSSPageSize: false,
  paperWidth: 210 * MM,
  paperHeight: 297 * MM,
  marginTop: 22 * MM,
  marginBottom: 20 * MM,
  marginLeft: 20 * MM,
  marginRight: 20 * MM,
  displayHeaderFooter: true,
  headerTemplate,
  footerTemplate,
});

if (!out.result || !out.result.data) {
  throw new Error('printToPDF returned nothing: ' + JSON.stringify(out).slice(0, 400));
}

const buf = Buffer.from(out.result.data, 'base64');
writeFileSync(pdfPath, buf);
console.log('pdf   : %s  (%d bytes)', pdfPath, buf.length);

try {
  ws.close();
} catch {
  /* ignore */
}
edge.kill();
