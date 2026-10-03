/**
 * Single source of truth for every user-facing string.
 *
 * Every entry carries both languages, and nothing renders a literal: a
 * component asks `useLabel()` for a key and the hook decides which spelling to
 * hand back. That means "there is no Chinese left in English mode" is a claim
 * the browser check can make by scanning the DOM, rather than a promise about
 * how carefully the components were written.
 *
 * Two functions sit under the hook:
 *
 * * `lookupLabel(key)`  - key -> the `{zh, en}` pair (or `undefined`);
 * * `renderLabel(pair, language)` - pair + language -> the one string to show.
 *
 * `profileFieldLabels` and `moduleLabels` are looked up through the same path,
 * so a profile field's caption is translated by exactly the same mechanism as a
 * button's.
 */

import { MODULE_LABELS } from "../types";

import type { Language } from "../storage";

export interface Label {
  zh: string;
  en: string;
}

/** The one place the three display modes are turned into a string. */
export function renderLabel(label: Label | undefined, language: Language): string {
  if (!label) return "";
  if (language === "zh") return label.zh;
  if (language === "en") return label.en;
  // `bilingual`: both, Chinese first. This is the shape the panel shipped with.
  return `${label.zh} (${label.en})`;
}

export const labels = {
  /* ------------------------------------------------------------ app chrome */
  appTitle: { zh: "简历-JD 自动填写助手", en: "Resume-JD auto-fill assistant" },
  appSubtitle: {
    zh: "仅从你自己的资料起草建议，永不提交表单，永不编造信息。",
    en: "Drafts suggestions from your own profile only. Never submits a form, never invents information.",
  },

  /* ----------------------------------------------------------- ui language */
  // The three toggle captions are deliberately ASCII. A language switcher that
  // reads "中 / EN / 双" puts Chinese characters on screen in English mode, which
  // makes "the panel shows no Chinese in English mode" unverifiable - so the
  // captions are language tags, and the readable names live in `langZh`,
  // `langEn` and `langBilingual`, which are used for `aria-label`/`title` and
  // therefore *are* translated.
  language: { zh: "界面语言", en: "Interface language" },
  langZh: { zh: "中文", en: "Chinese" },
  langEn: { zh: "英文", en: "English" },
  langBilingual: { zh: "中英双语", en: "Chinese and English together" },

  /* ------------------------------------------------------------ flow strip */
  flowTitle: { zh: "当前步骤", en: "Current step" },
  stepAuthorise: { zh: "授权", en: "Authorise" },
  stepProfile: { zh: "个人资料", en: "Profile" },
  stepScan: { zh: "扫描页面", en: "Scan" },
  stepJd: { zh: "职位描述", en: "Job description" },
  stepGenerate: { zh: "生成建议", en: "Generate" },
  stepReview: { zh: "审阅", en: "Review" },
  stepFill: { zh: "填入", en: "Fill" },

  /* --------------------------------------------------------------- settings */
  settings: { zh: "设置", en: "Settings" },
  baseUrl: { zh: "后端地址", en: "Backend base URL" },
  baseUrlHint: { zh: "默认 http://127.0.0.1:8765", en: "Default http://127.0.0.1:8765" },
  token: { zh: "访问令牌", en: "Access token" },
  tokenHint: {
    zh: "由后端在启动时打印，保存在 artifacts/server_token.txt",
    en: "Printed by the backend at startup; stored in artifacts/server_token.txt",
  },
  apiKey: { zh: "OpenRouter API 密钥", en: "OpenRouter API key" },
  apiKeyHint: {
    zh: "仅存储在本浏览器，除本地后端外不会发送到任何地方。",
    en: "Stored only in this browser, never sent anywhere except the local backend.",
  },
  condition: { zh: "模式", en: "Condition" },
  conditionA: { zh: "A：规则，无模型", en: "A: rules, no model" },
  conditionB: { zh: "B：仅模型", en: "B: model only" },
  conditionC: { zh: "C：模型 + 检索（默认）", en: "C: model + retrieval (default)" },

  /* ----------------------------------------------------------- status banner */
  connection: { zh: "连接状态", en: "Connection status" },
  backendUp: { zh: "后端在线", en: "Backend up" },
  backendDown: { zh: "后端离线", en: "Backend down" },
  modeLive: { zh: "实时 API", en: "live API" },
  modeOffline: { zh: "离线桩", en: "offline stub" },
  offlineWarning: {
    zh: "警告：离线桩模式。建议来自确定性桩，并非模型生成。",
    en: "Warning: offline stub mode. Suggestions come from a deterministic stub, not a model.",
  },
  model: { zh: "模型", en: "Model" },
  authRequired: { zh: "需要令牌", en: "auth required" },
  noAuth: { zh: "无需令牌", en: "no auth" },
  tabUsable: { zh: "当前标签页有可用表单", en: "Current tab has a usable form" },
  tabNotUsable: { zh: "当前标签页无可用表单", en: "No usable form in current tab" },
  recheck: { zh: "重新检测", en: "Re-check" },
  scannedFields: { zh: "已扫描字段", en: "Scanned fields" },
  unknown: { zh: "未知", en: "unknown" },

  /* ------------------------------------------------------------ authorisation */
  authorisation: { zh: "授权", en: "Authorisation" },
  authorisationNote: {
    zh: "仅勾选的模块会被读取、上传并发送给 AI。取消勾选将立即停止使用该模块。",
    en: "Only ticked modules are read, uploaded and sent to the AI. Unticking a module stops it being used immediately.",
  },
  revokeAll: { zh: "全部撤销", en: "Revoke all" },

  /* ----------------------------------------------------------------- profile */
  profile: { zh: "个人资料", en: "Profile" },
  profileNote: {
    zh: "点击“生成”前不会上传任何内容；资料仅保存在本浏览器中。",
    en: "Nothing is uploaded until you click Generate; inputs are held in this browser only.",
  },
  add: { zh: "添加", en: "Add" },
  remove: { zh: "删除", en: "Remove" },

  /* -------------------------------------------------------------------- jd */
  jd: { zh: "职位描述 (JD)", en: "Job description (JD)" },
  jdNote: { zh: "JD 为可选项，仅用于定制建议。", en: "The JD is optional and only used for tailoring." },
  jdPaste: { zh: "粘贴职位描述", en: "Paste job description" },
  jdUrl: { zh: "JD 链接", en: "JD URL" },
  fetch: { zh: "获取", en: "Fetch" },
  fetching: { zh: "获取中…", en: "Fetching…" },
  fetchedTitle: { zh: "已获取标题", en: "Fetched title" },
  chars: { zh: "字符数", en: "characters" },

  /* ------------------------------------------------------------------ scan */
  scan: { zh: "扫描页面", en: "Scan page" },
  scanning: { zh: "扫描中…", en: "Scanning…" },
  scanSummary: { zh: "字段统计", en: "Field summary" },

  /* -------------------------------------------------------------- generate */
  generate: { zh: "生成建议", en: "Generate suggestions" },
  generating: { zh: "生成中…", en: "generating…" },

  /* ------------------------------------------------------------ field table */
  fieldTable: { zh: "字段建议", en: "Field suggestions" },
  colLabel: { zh: "标签", en: "Label" },
  colState: { zh: "状态", en: "State" },
  colSuggested: { zh: "建议值", en: "Suggested value" },
  colSource: { zh: "来源", en: "Source" },
  colRelevance: { zh: "JD 相关", en: "JD relevance" },
  colConfidence: { zh: "置信度", en: "Confidence" },
  colRequired: { zh: "必填", en: "Required" },
  colMaxLen: { zh: "最大长度", en: "Max length" },
  colActions: { zh: "操作", en: "Actions" },
  confirm: { zh: "确认", en: "Confirm" },
  confirmed: { zh: "已确认", en: "Confirmed" },
  fillThis: { zh: "填入此字段", en: "Fill this field" },
  copy: { zh: "复制", en: "Copy" },
  copied: { zh: "已复制", en: "Copied" },
  fillCheck: { zh: "已填入页面", en: "written into the page" },
  locate: { zh: "定位", en: "Locate" },
  fillAllConfirmed: { zh: "填入所有已确认", en: "Fill all confirmed" },
  editedMarker: { zh: "已修改", en: "edited" },
  regenerateReplace: { zh: "重新生成并替换", en: "Regenerate and replace" },
  sensitiveWarning: { zh: "极敏感，请手动填写", en: "Extremely sensitive, fill in manually" },
  alreadyFilledNote: {
    zh: "该字段已有你填写的内容，助手不会覆盖。",
    en: "This field already holds your typing; the assistant will not overwrite it.",
  },
  fallbackNote: {
    zh: "部分字段无法自动填入，请复制后手动粘贴。",
    en: "Some fields could not be filled automatically; copy and paste them manually.",
  },

  /* -------------------------------------------------------- server warnings */
  warnings: { zh: "服务器提示", en: "Server notes" },
  riskFlags: { zh: "风险标记", en: "Risk flags" },
  overallSuggestions: { zh: "总体建议", en: "Overall suggestions" },
  notes: { zh: "备注", en: "Notes" },
  privacy: { zh: "隐私回显", en: "Privacy echo" },
  authorisedModules: { zh: "已授权模块", en: "Authorised modules" },
  usedModules: { zh: "已使用模块", en: "Used modules" },
  droppedModules: { zh: "已丢弃模块", en: "Dropped modules" },
  droppedWarning: {
    zh: "检测到被丢弃的模块，这可能是错误，请检查授权设置。",
    en: "A dropped module was detected; this may indicate a bug. Check your authorisation settings.",
  },
  jdAnalysis: { zh: "JD 分析", en: "JD analysis" },
  jobTitle: { zh: "职位名称", en: "Job title" },
  company: { zh: "公司", en: "Company" },
  location: { zh: "地点", en: "Location" },
  responsibilities: { zh: "职责", en: "Responsibilities" },
  requirements: { zh: "要求", en: "Requirements" },
  keywords: { zh: "关键词", en: "Keywords" },
  bonusPoints: { zh: "加分项", en: "Bonus points" },
  missingFromProfile: { zh: "资料中缺失", en: "Missing from your profile" },

  /* ---------------------------------------------------------- resume upload */
  resumeTitle: { zh: "简历上传", en: "Resume upload" },
  resumeHint: {
    zh: "拖入 PDF 或点击选择文件。PDF 不会离开浏览器，只有解析出的文字会发送到本地后端。",
    en: "Drop a PDF here, or click to choose one. The PDF never leaves the browser; only the text read out of it is sent to the local backend.",
  },
  resumeChoose: { zh: "选择 PDF 文件", en: "Choose a PDF file" },
  resumeParsing: { zh: "正在解析 PDF…", en: "Reading the PDF…" },
  resumeExtracting: { zh: "正在提取资料…", en: "Extracting your profile…" },
  resumeNoText: {
    zh: "这个 PDF 里没有可读取的文字，可能是扫描件。",
    en: "No text could be read from this PDF; it may be a scan.",
  },
  resumeTooLarge: { zh: "文件超过 8 MB 上限。", en: "The file is over the 8 MB limit." },
  resumeParseFailed: { zh: "无法解析这个 PDF。", en: "This PDF could not be read." },
  resumeFound: { zh: "已提取字段", en: "Fields extracted" },
  resumeUncertain: { zh: "请重点核对", en: "Worth checking" },
  resumeApply: { zh: "使用这份资料", en: "Use this profile" },
  resumeApplied: {
    zh: "已写入个人资料，请核对。",
    en: "Written into the profile; please check it.",
  },
  sourceUploaded: {
    zh: "个人资料来自刚才上传的简历。",
    en: "The profile came from the resume you just uploaded.",
  },

  /* ------------------------------------------------------------- misc */
  error: { zh: "错误", en: "Error" },
  noFields: { zh: "尚无字段。请先扫描页面并生成建议。", en: "No fields yet. Scan the page and generate suggestions first." },
  none: { zh: "无", en: "none" },
  yes: { zh: "是", en: "Yes" },
  no: { zh: "否", en: "No" },
  bgNoResponse: {
    zh: "背景服务工作线程未返回响应",
    en: "the background worker returned no response",
  },
  copyFailed: { zh: "复制失败", en: "copy failed" },

  /* --------------------------------------------------------------- chips */
  chipOffered: { zh: "已提供", en: "offered" },
  chipSensitive: { zh: "敏感已跳过", en: "sensitive skipped" },
  chipMissing: { zh: "缺失", en: "missing" },
  chipDeclined: { zh: "低置信度放弃", en: "declined (low confidence)" },
  chipNotFillable: { zh: "不可填写", en: "not fillable" },
  chipAlreadyFilled: { zh: "已填写", en: "already filled" },
};

/** Per-field labels for the profile form, keyed by the profile key. */
export const profileFieldLabels: Record<string, Label> = {
  full_name: { zh: "姓名", en: "Full name" },
  email: { zh: "邮箱", en: "Email" },
  phone: { zh: "电话", en: "Phone" },
  location: { zh: "所在地", en: "Location" },
  linkedin: { zh: "LinkedIn", en: "LinkedIn" },
  github: { zh: "GitHub", en: "GitHub" },
  portfolio: { zh: "作品集", en: "Portfolio" },
  school: { zh: "学校", en: "School" },
  degree: { zh: "学位", en: "Degree" },
  major: { zh: "专业", en: "Major" },
  start: { zh: "开始", en: "Start" },
  end: { zh: "结束", en: "End" },
  gpa: { zh: "成绩", en: "GPA" },
  employer: { zh: "雇主", en: "Employer" },
  title: { zh: "职位", en: "Title" },
  summary: { zh: "描述", en: "Summary" },
  name: { zh: "名称", en: "Name" },
  role: { zh: "角色", en: "Role" },
  link: { zh: "链接", en: "Link" },
};

/** Field keys, in display order, for each repeatable profile module. */
export const profileFieldOrder: Record<"education" | "internship" | "projects", string[]> = {
  education: ["school", "degree", "major", "start", "end", "gpa"],
  internship: ["employer", "title", "start", "end", "summary"],
  projects: ["name", "role", "summary", "link"],
};

/**
 * The four authorisable modules, under the same `{zh, en}` shape as everything
 * else.
 *
 * `MODULE_LABELS` in `types.ts` already holds these strings (they were there
 * before the language switch existed), so this is a narrowing of that record
 * rather than a second copy. One spelling of "Personal information", not two.
 */
export const moduleLabels: Record<string, Label> = MODULE_LABELS;

/**
 * Resolve a key to its `{zh, en}` pair.
 *
 * Three tables, one lookup, and two namespaces:
 *
 * * a bare key              -> `labels` (the panel's own strings);
 * * `"field.<key>"`         -> `profileFieldLabels` (a profile input's caption);
 * * `"module.<name>"`       -> `moduleLabels` (an authorisable module's name).
 *
 * The namespaces are not decoration. `location` exists in both `labels` (the
 * posting's location, in the JD analysis block) and `profileFieldLabels` (the
 * candidate's own location, on the profile form), and they are different
 * strings. A flat lookup silently resolved the profile form's caption to the JD
 * block's wording; the prefix makes the collision impossible to reintroduce.
 */
export function lookupLabel(key: string): Label | undefined {
  if (key.startsWith("field.")) return profileFieldLabels[key.slice("field.".length)];
  if (key.startsWith("module.")) return moduleLabels[key.slice("module.".length)];
  return (labels as unknown as Record<string, Label>)[key];
}
