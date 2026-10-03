/**
 * The only place the extension talks to the local backend.
 *
 * Used from the background service worker. The panel never calls this directly,
 * so the token is handled in exactly one module.
 *
 * Three behaviours worth naming:
 *
 * * **A non-2xx response is an error, not data.** A 401 (bad token) or a 422
 *   (bad request) must surface with its `detail`, because the alternative is the
 *   panel rendering an empty result as though the backend had answered.
 * * **Every request carries the token header** when one is configured, and the
 *   API key in its own header. The key is passed per request and never stored on
 *   the server.
 * * **The base URL is loopback-only.** A settings field that pointed at a remote
 *   host would send a candidate's profile to that host, so it is refused here as
 *   well as in the manifest's `host_permissions`.
 */

import type {
  ExtractResumeResponse,
  GenerateResponse,
  HealthResponse,
  JdFetchResponse,
  GenerateResponseEnvelope,
} from "./types";
import type { ExtensionSettings } from "./types";

export const TOKEN_HEADER = "X-RJD-Token";
export const API_KEY_HEADER = "X-RJD-Api-Key";

export class BackendError extends Error {
  readonly status: number;
  readonly detail: string;

  constructor(status: number, detail: string) {
    super(detail);
    this.name = "BackendError";
    this.status = status;
    this.detail = detail;
  }
}

/** Loopback check, mirroring `server/security.py`. */
export function isLoopbackBaseUrl(baseUrl: string): boolean {
  try {
    const url = new URL(baseUrl);
    const host = url.hostname;
    return (
      (url.protocol === "http:" || url.protocol === "https:") &&
      (host === "127.0.0.1" || host === "::1" || host === "localhost")
    );
  } catch {
    return false;
  }
}

function normaliseBase(baseUrl: string): string {
  const trimmed = (baseUrl || "").trim().replace(/\/+$/, "");
  return isLoopbackBaseUrl(trimmed) ? trimmed : "";
}

export interface CallOptions {
  timeoutMs?: number;
}

async function call<T>(
  path: string,
  body: unknown,
  settings: ExtensionSettings,
  options: CallOptions = {},
): Promise<T> {
  const base = normaliseBase(settings.baseUrl);
  if (!base) {
    throw new BackendError(
      0,
      `The backend address must be loopback (http://127.0.0.1:<port>). Got ${settings.baseUrl || "(empty)"}.`,
    );
  }

  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (settings.token) headers[TOKEN_HEADER] = settings.token;
  if (settings.apiKey) headers[API_KEY_HEADER] = settings.apiKey;

  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), options.timeoutMs ?? 120_000);

  let response: Response;
  try {
    response = await fetch(`${base}${path}`, {
      method: body === undefined ? "GET" : "POST",
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: controller.signal,
    });
  } catch (error) {
    const name = (error as { name?: string }).name ?? "Error";
    if (name === "AbortError") {
      throw new BackendError(0, `The backend did not answer within the time limit (${path}).`);
    }
    throw new BackendError(
      0,
      `Could not reach the local backend at ${base}. Start it with: python -m server.app`,
    );
  } finally {
    clearTimeout(timeout);
  }

  const text = await response.text();
  let payload: unknown = null;
  if (text) {
    try {
      payload = JSON.parse(text);
    } catch {
      payload = null;
    }
  }

  if (!response.ok) {
    const detail =
      (payload && typeof payload === "object" && "detail" in payload
        ? String((payload as { detail: unknown }).detail)
        : "") || `HTTP ${response.status} from ${path}`;
    throw new BackendError(response.status, detail);
  }
  return payload as T;
}

export async function health(settings: ExtensionSettings): Promise<HealthResponse> {
  return call<HealthResponse>("/health", undefined, settings, { timeoutMs: 8_000 });
}

export interface ScanFieldPayload {
  field_id?: string;
  tag: string;
  type: string;
  name: string;
  id: string;
  label: string;
  placeholder: string;
  aria_label: string;
  required: boolean;
  max_length: number | null;
  options: string[];
  help_text: string;
  current_value: string;
  selector: string;
}

export interface GeneratePayload {
  fields: ScanFieldPayload[];
  authorised_modules: string[];
  profile: Record<string, unknown>;
  jd_text: string;
  jd_url: string;
  condition: string;
  url: string;
  page_title: string;
  overwrite_filled: boolean;
}

export async function scan(
  payload: { url: string; page_title: string; fields: ScanFieldPayload[] },
  settings: ExtensionSettings,
): Promise<import("./types").ScanResponse> {
  return call<import("./types").ScanResponse>("/scan", payload, settings, { timeoutMs: 20_000 });
}

export async function generate(
  payload: GeneratePayload,
  settings: ExtensionSettings,
): Promise<GenerateResponse> {
  return call<GenerateResponse>("/generate", payload, settings);
}

export async function fetchJd(
  payload: { url: string; ignore_robots?: boolean },
  settings: ExtensionSettings,
): Promise<JdFetchResponse> {
  return call<JdFetchResponse>("/jd/fetch", payload, settings, { timeoutMs: 30_000 });
}

/**
 * Ask the backend to read a profile out of resume text.
 *
 * Takes text, not a file: the PDF is parsed in the panel by PDF.js and only the
 * text crosses the loopback boundary. That keeps the promise the privacy design
 * makes - the original document never leaves the browser - and it also keeps the
 * server free of any file-handling surface, which is what lets it stay
 * stateless without an exception for uploads.
 */
export async function extractResume(
  payload: { text: string },
  settings: ExtensionSettings,
): Promise<ExtractResumeResponse> {
  return call<ExtractResumeResponse>("/extract_resume", payload, settings, { timeoutMs: 30_000 });
}

/** Unwraps a `PanelResponse`-shaped payload, throwing on the failure branch. */
export function unwrap<T>(envelope: GenerateResponseEnvelope | { ok: boolean; data?: unknown; error?: string }): T {
  if (!envelope.ok || envelope.data === undefined) {
    throw new BackendError(0, envelope.error ?? "the background worker returned no data");
  }
  return envelope.data as T;
}
