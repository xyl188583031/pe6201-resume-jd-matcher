/**
 * `chrome.storage.local` wrapper.
 *
 * Two rules enforced here rather than left to each caller:
 *
 * 1. **Extremely sensitive values are never stored.** The assistant does not
 *    accept document numbers at all, and this module strips anything that looks
 *    like one out of the profile before it is written. A user who pastes their
 *    passport number into an unlabelled box would otherwise have it persisted in
 *    browser storage for good - a far worse outcome than a blank field.
 * 2. **The API key is stored, the token is stored, nothing else secret is.** The
 *    key is needed for the model call and lives only here and in the backend's
 *    environment; it is never written to disk by the backend.
 * 3. **The UI language lives under its own key.** A display preference is not
 *    profile data: clearing the profile must not reset it, and a language change
 *    must not rewrite `rjd_state_v1`. See the `Language` section at the bottom.
 */

import {
  DEFAULT_SETTINGS,
  EMPTY_PROFILE,
  NOTHING_AUTHORISED,
  type Authorisation,
  type PersistedState,
  type UserProfile,
} from "./types";

const STORAGE_KEY = "rjd_state_v1";

export const DEFAULT_STATE: PersistedState = {
  settings: { ...DEFAULT_SETTINGS },
  profile: { ...EMPTY_PROFILE },
  authorisation: { ...NOTHING_AUTHORISED },
  jdText: "",
  jdUrl: "",
  drafts: {},
};

/**
 * Field names that must never be persisted.
 *
 * Word-boundary anchored, and the separators are flattened first, so
 * `passportNo`, `passport_no` and `Passport Number` all fail the test - the same
 * treatment `server/field_map.py` gives them. `student_id` and `application_id`
 * are deliberately absent: they are institution-issued and routinely needed.
 */
const FORBIDDEN_KEY = new RegExp(
  [
    "passport",
    "national[ _-]?id",
    "identity[ _-]?(card|number|no)",
    "id[ _-]?(card|number|no)",
    "nric",
    "mykad",
    "aadhaar",
    "ssn",
    "social[ _-]?security",
    "residence[ _-]?permit",
    "tax[ _-]?(id|identification)",
    "licen[cs]e[ _-]?(number|no)",
  ].join("|"),
  "i",
);

const SAFE_ID = /(student|matric(ulation)?|enrol?ment|application|candidate|reference)[ _-]?(id|no|number)/i;

export function keyForbidden(key: string): boolean {
  const flat = key.replace(/[_\-.]+/g, " ").trim();
  if (SAFE_ID.test(flat)) return false;
  return FORBIDDEN_KEY.test(flat);
}

/** Drop any forbidden key, at any depth, before anything is written. */
export function stripForbidden<T>(value: T): T {
  if (Array.isArray(value)) {
    return value.map((item) => stripForbidden(item)) as unknown as T;
  }
  if (value && typeof value === "object") {
    const out: Record<string, unknown> = {};
    for (const [key, item] of Object.entries(value as Record<string, unknown>)) {
      if (keyForbidden(key)) continue;
      out[key] = stripForbidden(item);
    }
    return out as unknown as T;
  }
  return value;
}

function mergeState(raw: unknown): PersistedState {
  const candidate = (raw ?? {}) as Partial<PersistedState>;
  return {
    settings: { ...DEFAULT_SETTINGS, ...(candidate.settings ?? {}) },
    profile: {
      personal_info: { ...(candidate.profile?.personal_info ?? {}) },
      education: [...(candidate.profile?.education ?? [])],
      internship: [...(candidate.profile?.internship ?? [])],
      projects: [...(candidate.profile?.projects ?? [])],
    },
    authorisation: { ...NOTHING_AUTHORISED, ...(candidate.authorisation ?? {}) },
    jdText: candidate.jdText ?? "",
    jdUrl: candidate.jdUrl ?? "",
    drafts: { ...(candidate.drafts ?? {}) },
  };
}

export async function loadState(): Promise<PersistedState> {
  const stored = await chrome.storage.local.get(STORAGE_KEY);
  return mergeState(stored[STORAGE_KEY]);
}

export async function saveState(next: PersistedState): Promise<PersistedState> {
  const safe: PersistedState = {
    ...next,
    profile: stripForbidden<UserProfile>(next.profile),
  };
  await chrome.storage.local.set({ [STORAGE_KEY]: safe });
  return safe;
}

export async function patchState(patch: Partial<PersistedState>): Promise<PersistedState> {
  const current = await loadState();
  return saveState({
    ...current,
    ...patch,
    settings: { ...current.settings, ...(patch.settings ?? {}) },
    profile: { ...current.profile, ...(patch.profile ?? {}) },
    authorisation: {
      ...current.authorisation,
      ...(patch.authorisation ?? {}),
    } as Authorisation,
  });
}

export async function clearState(): Promise<void> {
  await chrome.storage.local.remove(STORAGE_KEY);
}

/* ------------------------------------------------------ pure state helpers */

/** The modules actually being sent, in a stable order. */
export function authorisedModules(authorisation: Authorisation): string[] {
  const order: (keyof Authorisation)[] = [
    "personal_info",
    "internship",
    "projects",
    "education",
  ];
  return order.filter((key) => authorisation[key]);
}

/**
 * Build the profile payload for a request.
 *
 * Only authorised modules are included. The server checks this again and reports
 * what it dropped, so this is the first of two gates rather than the only one -
 * but a module the user has not ticked should never leave the browser at all.
 */
export function profileForRequest(
  profile: UserProfile,
  authorisation: Authorisation,
): Partial<UserProfile> {
  const out: Partial<UserProfile> = {};
  if (authorisation.personal_info) out.personal_info = { ...profile.personal_info };
  if (authorisation.education) out.education = [...profile.education];
  if (authorisation.internship) out.internship = [...profile.internship];
  if (authorisation.projects) out.projects = [...profile.projects];
  return stripForbidden(out);
}

/* ------------------------------------------------------------- UI language */

/**
 * Which language the panel's own chrome is drawn in.
 *
 * Deliberately a *separate* storage key rather than a field of
 * `rjd_state_v1`. The two have different lifetimes: clearing the profile must
 * not reset a display preference, and adding a language field to the state
 * object would force a schema migration the next time it gains a value.
 *
 * `bilingual` is the default and the pre-existing behaviour, so an upgrade
 * changes nothing for a user who never touches the control.
 */
export type Language = "zh" | "en" | "bilingual";

const LANGUAGE_KEY = "uiLanguage";

export const DEFAULT_LANGUAGE: Language = "bilingual";

function asLanguage(value: unknown): Language {
  return value === "zh" || value === "en" || value === "bilingual" ? value : DEFAULT_LANGUAGE;
}

export async function getLanguage(): Promise<Language> {
  const stored = await chrome.storage.local.get(LANGUAGE_KEY);
  return asLanguage(stored[LANGUAGE_KEY]);
}

export async function setLanguage(lang: Language): Promise<void> {
  await chrome.storage.local.set({ [LANGUAGE_KEY]: asLanguage(lang) });
}
