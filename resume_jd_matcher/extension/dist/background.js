import { p as patchState, l as loadState, b as authorisedModules, c as profileForRequest } from "./assets/storage-CaMOGfzL.js";
const TOKEN_HEADER = "X-RJD-Token";
const API_KEY_HEADER = "X-RJD-Api-Key";
class BackendError extends Error {
  status;
  detail;
  constructor(status, detail) {
    super(detail);
    this.name = "BackendError";
    this.status = status;
    this.detail = detail;
  }
}
function isLoopbackBaseUrl(baseUrl) {
  try {
    const url = new URL(baseUrl);
    const host = url.hostname;
    return (url.protocol === "http:" || url.protocol === "https:") && (host === "127.0.0.1" || host === "::1" || host === "localhost");
  } catch {
    return false;
  }
}
function normaliseBase(baseUrl) {
  const trimmed = (baseUrl || "").trim().replace(/\/+$/, "");
  return isLoopbackBaseUrl(trimmed) ? trimmed : "";
}
async function call(path, body, settings, options = {}) {
  const base = normaliseBase(settings.baseUrl);
  if (!base) {
    throw new BackendError(
      0,
      `The backend address must be loopback (http://127.0.0.1:<port>). Got ${settings.baseUrl || "(empty)"}.`
    );
  }
  const headers = { "Content-Type": "application/json" };
  if (settings.token) headers[TOKEN_HEADER] = settings.token;
  if (settings.apiKey) headers[API_KEY_HEADER] = settings.apiKey;
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), options.timeoutMs ?? 12e4);
  let response;
  try {
    response = await fetch(`${base}${path}`, {
      method: body === void 0 ? "GET" : "POST",
      headers,
      body: body === void 0 ? void 0 : JSON.stringify(body),
      signal: controller.signal
    });
  } catch (error) {
    const name = error.name ?? "Error";
    if (name === "AbortError") {
      throw new BackendError(0, `The backend did not answer within the time limit (${path}).`);
    }
    throw new BackendError(
      0,
      `Could not reach the local backend at ${base}. Start it with: python -m server.app`
    );
  } finally {
    clearTimeout(timeout);
  }
  const text = await response.text();
  let payload = null;
  if (text) {
    try {
      payload = JSON.parse(text);
    } catch {
      payload = null;
    }
  }
  if (!response.ok) {
    const detail = (payload && typeof payload === "object" && "detail" in payload ? String(payload.detail) : "") || `HTTP ${response.status} from ${path}`;
    throw new BackendError(response.status, detail);
  }
  return payload;
}
async function health(settings) {
  return call("/health", void 0, settings, { timeoutMs: 8e3 });
}
async function scan(payload, settings) {
  return call("/scan", payload, settings, { timeoutMs: 2e4 });
}
async function generate(payload, settings) {
  return call("/generate", payload, settings);
}
async function fetchJd(payload, settings) {
  return call("/jd/fetch", payload, settings, { timeoutMs: 3e4 });
}
async function extractResume(payload, settings) {
  return call("/extract_resume", payload, settings, { timeoutMs: 3e4 });
}
chrome.runtime.onInstalled.addListener(() => {
  chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: true }).catch(() => {
  });
});
function ok(data) {
  return { ok: true, data };
}
function fail(error) {
  return { ok: false, error };
}
function errorMessage(error) {
  if (error instanceof BackendError) return error.detail;
  if (error instanceof Error) return error.message;
  return String(error);
}
async function activeTab() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  return tab ?? null;
}
function tabIsScriptable(url) {
  if (!url) return false;
  return /^https?:\/\//i.test(url);
}
async function sendToTab(tabId, message) {
  try {
    const response = await chrome.tabs.sendMessage(tabId, message);
    if (response === void 0) {
      throw new Error("the page did not answer (reload the tab and try again)");
    }
    return response;
  } catch (error) {
    throw new Error(
      `could not reach the page's content script. Reload the tab, then press scan again. (${errorMessage(error)})`
    );
  }
}
async function handleScan() {
  const tab = await activeTab();
  if (!tab?.id) return fail("no active tab");
  if (!tabIsScriptable(tab.url)) {
    return fail("This page does not allow extensions to read it. Open a normal http(s) application form.");
  }
  try {
    const page = await sendToTab(tab.id, { type: "RJD_SCAN_PAGE" });
    if (!page?.ok) return fail(page?.error ?? "the page scan failed");
    return ok(page);
  } catch (error) {
    return fail(errorMessage(error));
  }
}
async function handleGenerate(overwriteFilled) {
  const state = await loadState();
  const tab = await activeTab();
  if (!tab?.id) return fail("no active tab");
  if (!tabIsScriptable(tab.url)) {
    return fail("This page does not allow extensions to read it. Open a normal http(s) application form.");
  }
  let page;
  try {
    page = await sendToTab(tab.id, { type: "RJD_SCAN_PAGE" });
    if (!page?.ok) return fail(page?.error ?? "the page scan failed");
  } catch (error) {
    return fail(errorMessage(error));
  }
  if (!page.fields.length) {
    return fail("No fillable fields were found on this page. Nothing was sent to the model.");
  }
  const authorised = authorisedModules(state.authorisation);
  if (!authorised.length) {
    return fail("Tick at least one profile module first. Nothing was read, uploaded or sent.");
  }
  try {
    const response = await generate(
      {
        fields: page.fields.map((field) => ({ ...field })),
        authorised_modules: authorised,
        // Assembled here, not accepted from the panel: an unticked module must not
        // be able to reach the request through a UI bug.
        profile: profileForRequest(state.profile, state.authorisation),
        jd_text: state.jdText ?? "",
        jd_url: state.jdUrl ?? "",
        condition: state.settings.condition,
        url: page.url,
        page_title: page.pageTitle,
        overwrite_filled: overwriteFilled
      },
      state.settings
    );
    return ok(response);
  } catch (error) {
    return fail(errorMessage(error));
  }
}
async function handleServerScan(fields, url, pageTitle) {
  const state = await loadState();
  try {
    return await scan({ url, page_title: pageTitle, fields: fields.map((f) => ({ ...f })) }, state.settings);
  } catch {
    return null;
  }
}
async function handleJdFetch(url, ignoreRobots) {
  const state = await loadState();
  if (!url.trim()) return fail("Enter a job posting URL first.");
  try {
    const result = await fetchJd({ url: url.trim(), ignore_robots: ignoreRobots }, state.settings);
    return ok(result);
  } catch (error) {
    return fail(errorMessage(error));
  }
}
async function handleExtractResume(text) {
  if (!text.trim()) {
    return fail("The resume text came through empty, so nothing was sent.");
  }
  const state = await loadState();
  try {
    return ok(await extractResume({ text }, state.settings));
  } catch (error) {
    return fail(errorMessage(error));
  }
}
async function handleFill(values) {
  const tab = await activeTab();
  if (!tab?.id) return fail("no active tab");
  const trimmed = {};
  for (const [fieldId, value] of Object.entries(values ?? {})) {
    if (typeof value === "string" && value.length) trimmed[fieldId] = value;
  }
  if (!Object.keys(trimmed).length) return fail("Nothing was confirmed, so nothing was written.");
  try {
    const result = await sendToTab(tab.id, {
      type: "RJD_FILL_FIELDS",
      values: trimmed
    });
    return ok(result);
  } catch (error) {
    return fail(errorMessage(error));
  }
}
async function handleHighlight(fieldId) {
  const tab = await activeTab();
  if (!tab?.id) return fail("no active tab");
  try {
    const result = await sendToTab(tab.id, {
      type: "RJD_HIGHLIGHT_FIELD",
      field_id: fieldId
    });
    return ok(result);
  } catch (error) {
    return fail(errorMessage(error));
  }
}
async function handlePing() {
  const state = await loadState();
  const tab = await activeTab();
  const result = {
    backendUp: false,
    health: null,
    tabUsable: tabIsScriptable(tab?.url),
    scannedFields: 0
  };
  try {
    result.health = await health(state.settings);
    result.backendUp = true;
  } catch (error) {
    result.error = errorMessage(error);
  }
  if (tab?.id && result.backendUp) {
    try {
      const page = await sendToTab(tab.id, { type: "RJD_SCAN_PAGE" });
      result.scannedFields = page?.fields?.length ?? 0;
    } catch {
      result.scannedFields = 0;
    }
  }
  return ok(result);
}
async function handle(request) {
  switch (request?.type) {
    case "RJD_PING":
      return handlePing();
    case "RJD_GET_STATE":
      try {
        return ok(await loadState());
      } catch (error) {
        return fail(errorMessage(error));
      }
    case "RJD_SAVE_STATE":
      try {
        return ok(await patchState(request.patch));
      } catch (error) {
        return fail(errorMessage(error));
      }
    case "RJD_SCAN": {
      const scanned = await handleScan();
      if (!scanned.ok || !scanned.data) return scanned;
      const normalised = await handleServerScan(
        scanned.data.fields,
        scanned.data.url,
        scanned.data.pageTitle
      );
      const payload = { ...scanned.data, normalised };
      return ok(payload);
    }
    case "RJD_GENERATE":
      return handleGenerate(Boolean(request.overwriteFilled));
    case "RJD_JD_FETCH":
      return handleJdFetch(request.url, Boolean(request.ignoreRobots));
    case "RJD_EXTRACT_RESUME":
      return handleExtractResume(request.text);
    case "RJD_FILL":
      return handleFill(request.values);
    case "RJD_HIGHLIGHT":
      return handleHighlight(request.fieldId);
    default:
      return fail(`unknown request ${String(request?.type)}`);
  }
}
function fromPanelPage(sender) {
  const own = chrome.runtime.getURL("");
  return typeof sender.url === "string" && sender.url.startsWith(own);
}
chrome.runtime.onMessage.addListener(
  (message, sender, sendResponse) => {
    if (!fromPanelPage(sender)) return false;
    handle(message).then(sendResponse).catch((error) => sendResponse(fail(errorMessage(error))));
    return true;
  }
);
//# sourceMappingURL=background.js.map
