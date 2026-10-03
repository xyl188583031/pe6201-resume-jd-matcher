/**
 * Types mirroring `server/schemas.py`.
 *
 * These are a hand-written mirror rather than generated code, so the mapping is
 * written down explicitly: if a field is added on the server and not here, the
 * mismatch is visible in this file rather than silently dropped at runtime.
 *
 * The `added for the UI` comments mark keys the server sends that the task's
 * output schema does not specify. They exist so the extension can find a DOM
 * node again and can explain a withheld value; a consumer reading only the
 * specified keys is unaffected.
 */

export type Condition = "A" | "B" | "C";

/** The four independently-authorised profile modules (task section 3). */
export type ModuleName = "personal_info" | "internship" | "projects" | "education";

export const MODULE_NAMES: ModuleName[] = [
  "personal_info",
  "internship",
  "projects",
  "education",
];

export const MODULE_LABELS: Record<ModuleName, { en: string; zh: string }> = {
  personal_info: { en: "Personal information", zh: "个人信息" },
  internship: { en: "Internship experience", zh: "实习经历" },
  projects: { en: "Project experience", zh: "项目经历" },
  education: { en: "Education", zh: "教育背景" },
};

export type FieldTag = "input" | "textarea" | "select" | "contenteditable";

/* ------------------------------------------------------------------ /scan */

export interface RawField {
  field_id?: string;
  tag: FieldTag | string;
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
  /** What the field already holds; the user's own typing outranks the model. */
  current_value: string;
  selector: string;
  /**
   * The page locked this control (`readonly`). Reported so the server can mark
   * it not-fillable; its value is never read either, for the same reason a
   * password's is not - a value that can neither be reviewed nor edited is not
   * ours to send across the loopback boundary.
   */
  readonly: boolean;
  /**
   * The page disabled this control. Same family as `readonly` and the same two
   * consequences: the control is still reported, and its value is never read or
   * written. A disabled control cannot be typed into *and* the page will not
   * submit it, so a suggestion written here would be lost twice over.
   */
  disabled: boolean;
  /**
   * Text of the enclosing section (`<legend>` or a heading). **Context, never a
   * name.** The server uses it for exactly one thing: to veto the generic
   * `\bname\b` fallback, so a control called "Name" inside a section called
   * "Employer details" is not treated as the candidate's own name.
   */
  section_context: string;
}

export interface NormalizedField {
  field_id: string;
  label: string;
  tag: string;
  type: string;
  name: string;
  id: string;
  required: boolean;
  max_length: number | null;
  options: string[];
  help_text: string;
  current_value: string;
  selector: string;
  already_filled: boolean;
  fillable: boolean;
  skip_reason: string;
  category: string;
  module: ModuleName | null;
  fact_key: string | null;
  sensitive: boolean;
  sensitive_reason: string;
}

export interface ScanCounts {
  total: number;
  fillable: number;
  required: number;
  already_filled: number;
  sensitive: number;
  skipped: number;
}

export interface ScanResponse {
  url: string;
  page_title: string;
  counts: ScanCounts;
  fields: NormalizedField[];
  notes: string[];
}

/* ----------------------------------------------------------- jd_analysis */

export interface JDAnalysis {
  job_title: string;
  company: string;
  location: string;
  responsibilities: string[];
  requirements: string[];
  keywords: string[];
  bonus_points: string[];
  missing_from_user_profile: string[];
}

export const EMPTY_JD_ANALYSIS: JDAnalysis = {
  job_title: "",
  company: "",
  location: "",
  responsibilities: [],
  requirements: [],
  keywords: [],
  bonus_points: [],
  missing_from_user_profile: [],
};

/* ------------------------------------------------------------- /generate */

export interface FieldSuggestion {
  /* --- the specified schema ------------------------------------------- */
  field_id: string;
  label: string;
  type: string;
  required: boolean;
  max_length: number | null;
  suggested_value: string | null;
  source: string;
  jd_relevance: string;
  confidence: number;
  components_present: string[];
  needs_user_confirmation: boolean;
  missing: boolean;
  sensitive_skipped: boolean;
  message: string;

  /* --- added for the UI ------------------------------------------------ */
  tag: string;
  selector: string;
  current_value: string;
  already_filled: boolean;
  options: string[];
  abstained: boolean;
  reasons: string[];
  /**
   * False for a control the assistant must never touch (hidden, submit, reset,
   * file, password, unsupported element). Distinct from "we have no value for
   * it": a row with `fillable === false` must not offer a fill action at all.
   */
  fillable: boolean;
}

export interface GenerateCounts {
  total: number;
  suggestion_offered: number;
  withheld_low_confidence: number;
  missing: number;
  sensitive_skipped: number;
  already_filled: number;
  needs_confirmation: number;
  /**
   * Controls the assistant never touches. Together with
   * `suggestion_offered`, `withheld_low_confidence`, `missing` and
   * `sensitive_skipped` this partitions `total`; `already_filled` is orthogonal
   * and deliberately overlaps.
   */
  not_fillable: number;
}

export interface PrivacyEcho {
  authorised_modules: ModuleName[];
  used_modules: ModuleName[];
  dropped_modules: ModuleName[];
  in_memory_only: boolean;
  persisted: boolean;
}

export interface GenerateResponse {
  run_id: string;
  mode: string;
  model: string;
  condition: string;
  jd_analysis: JDAnalysis;
  overall_suggestions: string[];
  risk_flags: string[];
  fields: FieldSuggestion[];
  counts: GenerateCounts;
  privacy: PrivacyEcho;
  notes: string[];
}

/**
 * Why a suggestion carries no value. The three states are distinguishable on
 * purpose; collapsing them would make a skipped passport number look like a
 * field the assistant simply could not answer.
 */
export type WithholdReason =
  | "offered"
  | "sensitive_skipped"
  | "missing"
  | "declined_low_confidence"
  | "not_fillable"
  | "unconfirmed";

export function withholdReason(field: FieldSuggestion): WithholdReason {
  if (field.suggested_value !== null) return "offered";
  if (field.sensitive_skipped) return "sensitive_skipped";
  if (field.abstained) return "declined_low_confidence";
  if (field.missing) return "missing";
  if (!field.message) return "not_fillable";
  return "not_fillable";
}

/* -------------------------------------------------------------- /jd/fetch */

export interface JdFetchResponse {
  ok: boolean;
  url: string;
  final_url: string;
  status: number | null;
  content_type: string;
  title: string;
  text: string;
  chars: number;
  robots_allowed: boolean;
  reason: string;
  message: string;
}

/* ---------------------------------------------------------------- /health */

export interface HealthResponse {
  status: string;
  app: string;
  version: string;
  mode: string;
  model: string;
  bind_host: string;
  bind_port: number;
  auth_required: boolean;
  knowledge_base: Record<string, unknown> | null;
  sensitive_policy: Record<string, unknown>;
  privacy: Record<string, unknown>;
  prototype_banner: string;
  non_use_notice: string;
}

/* --------------------------------------------------------- local storage */

export interface PersonalInfo {
  full_name?: string;
  email?: string;
  phone?: string;
  location?: string;
  linkedin?: string;
  github?: string;
  portfolio?: string;
  [key: string]: string | undefined;
}

export interface EducationEntry {
  school?: string;
  degree?: string;
  major?: string;
  start?: string;
  end?: string;
  gpa?: string;
  [key: string]: string | undefined;
}

export interface ExperienceEntry {
  employer?: string;
  title?: string;
  start?: string;
  end?: string;
  summary?: string;
  [key: string]: string | undefined;
}

export interface ProjectEntry {
  name?: string;
  role?: string;
  summary?: string;
  link?: string;
  [key: string]: string | undefined;
}

/**
 * The user's profile. Held in `chrome.storage.local` and sent only for the
 * modules the user has ticked.
 *
 * Nothing here is ever pre-filled with a document number: there is no field for
 * one, because the assistant does not accept them at all.
 */
export interface UserProfile {
  personal_info: PersonalInfo;
  education: EducationEntry[];
  internship: ExperienceEntry[];
  projects: ProjectEntry[];
}

export const EMPTY_PROFILE: UserProfile = {
  personal_info: {},
  education: [],
  internship: [],
  projects: [],
};

export interface Authorisation {
  personal_info: boolean;
  internship: boolean;
  projects: boolean;
  education: boolean;
}

export const NOTHING_AUTHORISED: Authorisation = {
  personal_info: false,
  internship: false,
  projects: false,
  education: false,
};

export interface ExtensionSettings {
  baseUrl: string;
  token: string;
  /** Sent per request only, never stored on the server. */
  apiKey: string;
  condition: Condition;
  /** Section 7.3: off until the user asks for a field to be regenerated. */
  overwriteFilled: boolean;
}

export const DEFAULT_SETTINGS: ExtensionSettings = {
  baseUrl: "http://127.0.0.1:8765",
  token: "",
  apiKey: "",
  condition: "C",
  overwriteFilled: false,
};

/**
 * The user's per-field edit state.
 *
 * `edited` is what implements section 7.3: once a user touches a suggestion it
 * outranks the model, and a later generation must not silently replace it.
 */
export interface FieldDraft {
  field_id: string;
  value: string;
  edited: boolean;
  confirmed: boolean;
}

export type DraftMap = Record<string, FieldDraft>;

export interface PersistedState {
  settings: ExtensionSettings;
  profile: UserProfile;
  authorisation: Authorisation;
  jdText: string;
  jdUrl: string;
  /** Never contains a document number; those fields are not stored at all. */
  drafts: DraftMap;
}

/* --------------------------------------------------------- /extract_resume */

/**
 * A profile the server read out of resume text, for the user to confirm.
 *
 * `profile` is a `UserProfile`, deliberately: what comes back from an upload is
 * stored in exactly the slot the manual form writes to, so there is one profile
 * in the panel and not two that can disagree.
 *
 * `extracted_fields` and `uncertain_fields` carry dotted paths
 * (`personal_info.email`, `education[0].end`). The second list is what the
 * confirm step highlights: the extractor either guessed the value or could not
 * read it at all, and both mean "check this yourself".
 */
export interface ExtractResumeResponse {
  profile: UserProfile;
  extracted_fields: string[];
  uncertain_fields: string[];
  source: string;
  notes: string[];
}

/* --------------------------------------------------- background <-> content */

export interface ScanPageRequest {
  type: "RJD_SCAN_PAGE";
}

export interface ScanPageResult {
  ok: boolean;
  url: string;
  pageTitle: string;
  fields: RawField[];
  error?: string;
}

/**
 * A page scan plus the server's classification of it.
 *
 * `normalised` is what lets the panel show *why* a control will be left alone -
 * a hidden input, a password box, a field that already holds the user's typing -
 * instead of just omitting it.
 */
export interface ScanWithClassification extends ScanPageResult {
  normalised?: ScanResponse | null;
}

export interface FillFieldsRequest {
  type: "RJD_FILL_FIELDS";
  /** field_id -> the exact text to write. Only confirmed entries get here. */
  values: Record<string, string>;
}

export interface FillFieldResult {
  field_id: string;
  ok: boolean;
  /** True when the write could not be done and the UI must offer copy/paste. */
  fallback: boolean;
  reason: string;
}

export interface FillFieldsResult {
  ok: boolean;
  results: FillFieldResult[];
  error?: string;
}

export interface HighlightFieldRequest {
  type: "RJD_HIGHLIGHT_FIELD";
  field_id: string;
}

export interface HighlightFieldResult {
  ok: boolean;
  error?: string;
}

export type ContentRequest = ScanPageRequest | FillFieldsRequest | HighlightFieldRequest;

/**
 * Panel -> background requests.
 *
 * Every call to the backend goes through the background service worker, never
 * from the panel directly. Two reasons: the token is handled in one place, and
 * the service worker holds the host permission for `127.0.0.1`, so the panel
 * page never needs to be the thing that is trusted with network access.
 */
export type PanelRequest =
  | { type: "RJD_PING" }
  | { type: "RJD_GET_STATE" }
  | { type: "RJD_SAVE_STATE"; patch: Partial<PersistedState> }
  | { type: "RJD_SCAN" }
  | { type: "RJD_GENERATE"; overwriteFilled?: boolean }
  | { type: "RJD_JD_FETCH"; url: string; ignoreRobots?: boolean }
  | { type: "RJD_FILL"; values: Record<string, string> }
  | { type: "RJD_HIGHLIGHT"; fieldId: string }
  /**
   * Resume text the *panel* already extracted from a PDF with PDF.js. The PDF
   * itself never leaves the browser, and this message is the only way that text
   * reaches the backend.
   */
  | { type: "RJD_EXTRACT_RESUME"; text: string };

export type PanelRequestType = PanelRequest["type"];

export interface PanelResponse<T> {
  ok: boolean;
  data?: T;
  error?: string;
}

/** What `RJD_PING` returns: enough for the panel to configure itself. */
export interface PingResult {
  backendUp: boolean;
  health: HealthResponse | null;
  tabUsable: boolean;
  scannedFields: number;
  error?: string;
}

export type PingResponse = PanelResponse<PingResult>;
export type StateResponse = PanelResponse<PersistedState>;
export type ScanResponseEnvelope = PanelResponse<ScanWithClassification>;
export type GenerateResponseEnvelope = PanelResponse<GenerateResponse>;
export type JdFetchResponseEnvelope = PanelResponse<JdFetchResponse>;
export type FillResponseEnvelope = PanelResponse<FillFieldsResult>;
export type HighlightResponseEnvelope = PanelResponse<HighlightFieldResult>;

