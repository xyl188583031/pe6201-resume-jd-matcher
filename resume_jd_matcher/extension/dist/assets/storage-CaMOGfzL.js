const MODULE_LABELS = {
  personal_info: { en: "Personal information", zh: "个人信息" },
  internship: { en: "Internship experience", zh: "实习经历" },
  projects: { en: "Project experience", zh: "项目经历" },
  education: { en: "Education", zh: "教育背景" }
};
function withholdReason(field) {
  if (field.suggested_value !== null) return "offered";
  if (field.sensitive_skipped) return "sensitive_skipped";
  if (field.abstained) return "declined_low_confidence";
  if (field.missing) return "missing";
  if (!field.message) return "not_fillable";
  return "not_fillable";
}
const EMPTY_PROFILE = {
  personal_info: {},
  education: [],
  internship: [],
  projects: []
};
const NOTHING_AUTHORISED = {
  personal_info: false,
  internship: false,
  projects: false,
  education: false
};
const DEFAULT_SETTINGS = {
  baseUrl: "http://127.0.0.1:8765",
  token: "",
  apiKey: "",
  condition: "C",
  overwriteFilled: false
};
const STORAGE_KEY = "rjd_state_v1";
const DEFAULT_STATE = {
  settings: { ...DEFAULT_SETTINGS },
  profile: { ...EMPTY_PROFILE },
  authorisation: { ...NOTHING_AUTHORISED },
  jdText: "",
  jdUrl: "",
  drafts: {}
};
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
    "licen[cs]e[ _-]?(number|no)"
  ].join("|"),
  "i"
);
const SAFE_ID = /(student|matric(ulation)?|enrol?ment|application|candidate|reference)[ _-]?(id|no|number)/i;
function keyForbidden(key) {
  const flat = key.replace(/[_\-.]+/g, " ").trim();
  if (SAFE_ID.test(flat)) return false;
  return FORBIDDEN_KEY.test(flat);
}
function stripForbidden(value) {
  if (Array.isArray(value)) {
    return value.map((item) => stripForbidden(item));
  }
  if (value && typeof value === "object") {
    const out = {};
    for (const [key, item] of Object.entries(value)) {
      if (keyForbidden(key)) continue;
      out[key] = stripForbidden(item);
    }
    return out;
  }
  return value;
}
function mergeState(raw) {
  const candidate = raw ?? {};
  return {
    settings: { ...DEFAULT_SETTINGS, ...candidate.settings ?? {} },
    profile: {
      personal_info: { ...candidate.profile?.personal_info ?? {} },
      education: [...candidate.profile?.education ?? []],
      internship: [...candidate.profile?.internship ?? []],
      projects: [...candidate.profile?.projects ?? []]
    },
    authorisation: { ...NOTHING_AUTHORISED, ...candidate.authorisation ?? {} },
    jdText: candidate.jdText ?? "",
    jdUrl: candidate.jdUrl ?? "",
    drafts: { ...candidate.drafts ?? {} }
  };
}
async function loadState() {
  const stored = await chrome.storage.local.get(STORAGE_KEY);
  return mergeState(stored[STORAGE_KEY]);
}
async function saveState(next) {
  const safe = {
    ...next,
    profile: stripForbidden(next.profile)
  };
  await chrome.storage.local.set({ [STORAGE_KEY]: safe });
  return safe;
}
async function patchState(patch) {
  const current = await loadState();
  return saveState({
    ...current,
    ...patch,
    settings: { ...current.settings, ...patch.settings ?? {} },
    profile: { ...current.profile, ...patch.profile ?? {} },
    authorisation: {
      ...current.authorisation,
      ...patch.authorisation ?? {}
    }
  });
}
function authorisedModules(authorisation) {
  const order = [
    "personal_info",
    "internship",
    "projects",
    "education"
  ];
  return order.filter((key) => authorisation[key]);
}
function profileForRequest(profile, authorisation) {
  const out = {};
  if (authorisation.personal_info) out.personal_info = { ...profile.personal_info };
  if (authorisation.education) out.education = [...profile.education];
  if (authorisation.internship) out.internship = [...profile.internship];
  if (authorisation.projects) out.projects = [...profile.projects];
  return stripForbidden(out);
}
const LANGUAGE_KEY = "uiLanguage";
const DEFAULT_LANGUAGE = "bilingual";
function asLanguage(value) {
  return value === "zh" || value === "en" || value === "bilingual" ? value : DEFAULT_LANGUAGE;
}
async function getLanguage() {
  const stored = await chrome.storage.local.get(LANGUAGE_KEY);
  return asLanguage(stored[LANGUAGE_KEY]);
}
async function setLanguage(lang) {
  await chrome.storage.local.set({ [LANGUAGE_KEY]: asLanguage(lang) });
}
export {
  DEFAULT_LANGUAGE as D,
  MODULE_LABELS as M,
  DEFAULT_STATE as a,
  authorisedModules as b,
  profileForRequest as c,
  getLanguage as g,
  loadState as l,
  patchState as p,
  setLanguage as s,
  withholdReason as w
};
//# sourceMappingURL=storage-CaMOGfzL.js.map
