/**
 * Background service worker: the only place that talks to the network.
 *
 * Deliberately the sole owner of two things:
 *
 * * **the backend call**, so the access token and the API key are handled in one
 *   module and the panel page never needs network trust;
 * * **the profile payload**, assembled here from `chrome.storage.local` rather
 *   than passed in from the panel, so the unticked modules cannot be smuggled
 *   into a request by a UI bug. The server checks the same thing again and
 *   reports what it dropped.
 *
 * It holds no state between events. Every handler re-reads storage, because an
 * MV3 service worker is killed and restarted at will, and a cached profile would
 * silently outlive the user unticking a module.
 */

import * as api from "./api";
import { authorisedModules, loadState, patchState, profileForRequest } from "./storage";
import type {
  ExtractResumeResponse,
  FillFieldsResult,
  GenerateResponse,
  HighlightFieldResult,
  JdFetchResponse,
  PanelRequest,
  PanelResponse,
  PingResult,
  ScanPageResult,
  ScanWithClassification,
  ScanResponse,
} from "./types";

/* ------------------------------------------------------------- plumbing */

/** Give Chrome's own action click the side panel, so one click opens the tool. */
chrome.runtime.onInstalled.addListener(() => {
  chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: true }).catch(() => {
    /* Older builds lack setPanelBehavior; the panel still opens from the toolbar menu. */
  });
});

function ok<T>(data: T): PanelResponse<T> {
  return { ok: true, data };
}

function fail<T>(error: string): PanelResponse<T> {
  return { ok: false, error };
}

export function errorMessage(error: unknown): string {
  if (error instanceof api.BackendError) return error.detail;
  if (error instanceof Error) return error.message;
  return String(error);
}

async function activeTab(): Promise<chrome.tabs.Tab | null> {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  return tab ?? null;
}

/**
 * Can a content script run on this tab?
 *
 * Extensions cannot script `chrome://`, the Web Store, other extensions' pages
 * or local files without an explicit permission, and the content script is what
 * does the scanning and the writing - so there is nothing to offer on those
 * pages, and the panel should say so plainly instead of failing at fill time.
 */
export function tabIsScriptable(url: string | undefined): boolean {
  if (!url) return false;
  return /^https?:\/\//i.test(url);
}

async function sendToTab<T>(tabId: number, message: unknown): Promise<T> {
  try {
    const response = (await chrome.tabs.sendMessage(tabId, message)) as T | undefined;
    if (response === undefined) {
      throw new Error("the page did not answer (reload the tab and try again)");
    }
    return response;
  } catch (error) {
    throw new Error(
      "could not reach the page's content script. Reload the tab, then press scan again. " +
        `(${errorMessage(error)})`,
    );
  }
}

/* -------------------------------------------------------------- handlers */

async function handleScan(): Promise<PanelResponse<ScanPageResult>> {
  const tab = await activeTab();
  if (!tab?.id) return fail("no active tab");
  if (!tabIsScriptable(tab.url)) {
    return fail("This page does not allow extensions to read it. Open a normal http(s) application form.");
  }
  try {
    const page = await sendToTab<ScanPageResult>(tab.id, { type: "RJD_SCAN_PAGE" });
    if (!page?.ok) return fail(page?.error ?? "the page scan failed");
    return ok(page);
  } catch (error) {
    return fail(errorMessage(error));
  }
}

async function handleGenerate(
  overwriteFilled: boolean,
): Promise<PanelResponse<GenerateResponse>> {
  const state = await loadState();
  const tab = await activeTab();
  if (!tab?.id) return fail("no active tab");
  if (!tabIsScriptable(tab.url)) {
    return fail("This page does not allow extensions to read it. Open a normal http(s) application form.");
  }

  let page: ScanPageResult;
  try {
    page = await sendToTab<ScanPageResult>(tab.id, { type: "RJD_SCAN_PAGE" });
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
    const response = await api.generate(
      {
        fields: page.fields.map((field) => ({ ...field })),
        authorised_modules: authorised,
        // Assembled here, not accepted from the panel: an unticked module must not
        // be able to reach the request through a UI bug.
        profile: profileForRequest(state.profile, state.authorisation) as Record<string, unknown>,
        jd_text: state.jdText ?? "",
        jd_url: state.jdUrl ?? "",
        condition: state.settings.condition,
        url: page.url,
        page_title: page.pageTitle,
        overwrite_filled: overwriteFilled,
      },
      state.settings,
    );
    return ok(response);
  } catch (error) {
    return fail(errorMessage(error));
  }
}

async function handleServerScan(
  fields: ScanPageResult["fields"],
  url: string,
  pageTitle: string,
): Promise<ScanResponse | null> {
  const state = await loadState();
  try {
    return await api.scan({ url, page_title: pageTitle, fields: fields.map((f) => ({ ...f })) }, state.settings);
  } catch {
    // The scan endpoint is a convenience: the panel can render from the raw
    // fields. A failure here must not block generating.
    return null;
  }
}

async function handleJdFetch(
  url: string,
  ignoreRobots: boolean,
): Promise<PanelResponse<JdFetchResponse>> {
  const state = await loadState();
  if (!url.trim()) return fail("Enter a job posting URL first.");
  try {
    const result = await api.fetchJd({ url: url.trim(), ignore_robots: ignoreRobots }, state.settings);
    return ok(result);
  } catch (error) {
    return fail(errorMessage(error));
  }
}

/**
 * Read a profile out of resume text the panel already extracted.
 *
 * The PDF never reaches this function. The panel parses it with PDF.js in the
 * browser and sends only the resulting text, so the document stays on the
 * user's machine and this handler is a thin pass-through: settings from storage,
 * one call, nothing written back. The panel owns the confirm step, so an upload
 * cannot silently replace the profile the user has already reviewed - the worst
 * case is a response the user declines to apply.
 *
 * Refusing empty text here rather than letting the server 422 is deliberate: the
 * server's rejection is correct but generic, and "nothing was sent" is the more
 * useful thing for the panel to say.
 */
async function handleExtractResume(
  text: string,
): Promise<PanelResponse<ExtractResumeResponse>> {
  if (!text.trim()) {
    return fail("The resume text came through empty, so nothing was sent.");
  }
  const state = await loadState();
  try {
    return ok(await api.extractResume({ text }, state.settings));
  } catch (error) {
    return fail(errorMessage(error));
  }
}

async function handleFill(values: Record<string, string>): Promise<PanelResponse<FillFieldsResult>> {
  const tab = await activeTab();
  if (!tab?.id) return fail("no active tab");
  const trimmed: Record<string, string> = {};
  for (const [fieldId, value] of Object.entries(values ?? {})) {
    if (typeof value === "string" && value.length) trimmed[fieldId] = value;
  }
  if (!Object.keys(trimmed).length) return fail("Nothing was confirmed, so nothing was written.");
  try {
    const result = await sendToTab<FillFieldsResult>(tab.id, {
      type: "RJD_FILL_FIELDS",
      values: trimmed,
    });
    return ok(result);
  } catch (error) {
    return fail(errorMessage(error));
  }
}

async function handleHighlight(fieldId: string): Promise<PanelResponse<HighlightFieldResult>> {
  const tab = await activeTab();
  if (!tab?.id) return fail("no active tab");
  try {
    const result = await sendToTab<HighlightFieldResult>(tab.id, {
      type: "RJD_HIGHLIGHT_FIELD",
      field_id: fieldId,
    });
    return ok(result);
  } catch (error) {
    return fail(errorMessage(error));
  }
}

async function handlePing(): Promise<PanelResponse<PingResult>> {
  const state = await loadState();
  const tab = await activeTab();
  const result: PingResult = {
    backendUp: false,
    health: null,
    tabUsable: tabIsScriptable(tab?.url),
    scannedFields: 0,
  };

  try {
    result.health = await api.health(state.settings);
    result.backendUp = true;
  } catch (error) {
    result.error = errorMessage(error);
  }

  if (tab?.id && result.backendUp) {
    try {
      const page = await sendToTab<ScanPageResult>(tab.id, { type: "RJD_SCAN_PAGE" });
      result.scannedFields = page?.fields?.length ?? 0;
    } catch {
      result.scannedFields = 0;
    }
  }
  return ok(result);
}

export async function handle(request: PanelRequest): Promise<PanelResponse<unknown>> {
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
      // Also ask the server to classify, so the panel shows the same picture the
      // backend will use - including which controls it refuses to touch.
      const normalised = await handleServerScan(
        scanned.data.fields,
        scanned.data.url,
        scanned.data.pageTitle,
      );
      const payload: ScanWithClassification = { ...scanned.data, normalised };
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
      return fail(`unknown request ${String((request as { type?: string })?.type)}`);
  }
}

/**
 * Did this message come from one of the extension's own pages?
 *
 * The panel is the only thing allowed to drive the backend. A content script
 * must never be able to, or any page the user happens to have open could make
 * the worker spend their API key just by posting it a message - and content
 * scripts are responders, never initiators.
 *
 * The test is the sender's **url**, not the presence of `sender.tab`. A content
 * script reports the host page as its url; an extension page reports
 * `chrome-extension://<id>/...`, so the prefix separates the two exactly.
 *
 * Testing `sender.tab` instead was too broad, and it failed invisibly: opening
 * `chrome-extension://<id>/panel.html` as an ordinary tab - which is navigable,
 * and is how `browser_check.mjs` drives the panel - gives the panel page a `tab`
 * of its own, so the guard cut the panel off from the backend and every request
 * came back `undefined` with no error shown anywhere. The side panel itself has
 * no `tab`, which is why the bug never showed up there.
 */
function fromPanelPage(sender: chrome.runtime.MessageSender): boolean {
  const own = chrome.runtime.getURL("");
  return typeof sender.url === "string" && sender.url.startsWith(own);
}

chrome.runtime.onMessage.addListener(
  (message: PanelRequest, sender, sendResponse: (response: unknown) => void) => {
    if (!fromPanelPage(sender)) return false;
    handle(message)
      .then(sendResponse)
      .catch((error: unknown) => sendResponse(fail(errorMessage(error))));
    return true;
  },
);
