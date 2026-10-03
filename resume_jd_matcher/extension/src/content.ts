/**
 * Content script: read a page's form controls, and write into them on request.
 *
 * Self-contained by necessity. An MV3 content script is a classic script, so it
 * cannot contain `import` statements - which is why this file has no runtime
 * imports and every constant it needs is local. (`import type` is erased at
 * transpile time, so the type-only imports below are safe; the build is checked
 * for stray `import` statements afterwards.)
 *
 * Scope of what it reads: **form controls only.** It never reads page prose, and
 * it never reads a control's contents into a log. The scanner returns attributes
 * the DOM already exposes plus a bounded snippet of nearby *label* text, because
 * the backend cannot classify a field without knowing what it is called.
 *
 * What it refuses to do:
 *   * never click a submit, next-page or confirm button - the only elements it
 *     ever clicks are radio and checkbox inputs;
 *   * never write into a control that already holds a value unless the panel
 *     explicitly asked for that field;
 *   * never invent a value - it writes exactly the string it was given;
 *   * never write into a control the page has locked (`readonly`) or switched
 *     off (`disabled`). A value the user could not then edit is not a
 *     suggestion, it is a change they cannot undo: a `readonly` box is usually
 *     filled by the page's own script, and a disabled one is never submitted at
 *     all. Neither value is read either.
 */

import type {
  ContentRequest,
  FillFieldResult,
  FillFieldsRequest,
  FillFieldsResult,
  HighlightFieldRequest,
  HighlightFieldResult,
  RawField,
  ScanPageResult,
} from "./types";

/* ------------------------------------------------------------------ limits */

const MAX_FIELDS = 400;
const MAX_HELP_CHARS = 180;
const MAX_OPTIONS = 40;
const MAX_LABEL_CHARS = 200;
/** How far up the tree to look for a field's enclosing label text. */
const LABEL_ANCESTOR_DEPTH = 4;

/* -------------------------------------------------------------- field ids */

/**
 * The same id algorithm as `server/field_map.py:compute_field_id`.
 *
 * Both sides must agree: the panel stores the user's edits against these ids, so
 * an id that changed between a scan and a fill would silently discard the user's
 * typing. The server only computes an id when one is absent, so the id this
 * script sends is the id that comes back.
 *
 * `tag` is not in the basis on either side: it identifies nothing (every text
 * box on the page shares it), and including it made the `wf_anon_NNN` branch
 * unreachable because the string "input" is always a non-empty basis.
 */
async function computeFieldId(field: RawField, index: number): Promise<string> {
  const basis = [field.name, field.id, field.label, field.placeholder]
    .map((part) => (part ?? "").trim())
    .join("|");
  if (!basis.replace(/\|/g, "").trim()) {
    return `wf_anon_${String(index).padStart(3, "0")}`;
  }
  const digest = await sha1Hex(basis);
  return `wf_${digest.slice(0, 12)}`;
}

async function sha1Hex(text: string): Promise<string> {
  const bytes = new TextEncoder().encode(text);
  // crypto.subtle is unavailable on insecure origins, which is exactly where a
  // real application form lives. Fall back to a deterministic non-crypto hash:
  // ids only need to be stable and collision-free within one page, and a weaker
  // hash is strictly better than failing to scan.
  if (globalThis.crypto?.subtle) {
    const buffer = await globalThis.crypto.subtle.digest("SHA-1", bytes);
    return [...new Uint8Array(buffer)].map((b) => b.toString(16).padStart(2, "0")).join("");
  }
  let h1 = 0x811c9dc5;
  let h2 = 0x01000193;
  for (const byte of bytes) {
    h1 = (h1 ^ byte) >>> 0;
    h1 = (h1 * 0x01000193) >>> 0;
    h2 = (h2 + byte * 31) >>> 0;
  }
  return (h1.toString(16).padStart(8, "0") + h2.toString(16).padStart(8, "0")).repeat(2).slice(0, 40);
}

const elementMap = new Map<string, HTMLElement>();

/* ------------------------------------------------------------- scanning */

function isFillableControl(element: Element): element is HTMLElement {
  if (!(element instanceof HTMLElement)) return false;
  if (element.hidden) return false;
  if (element.getAttribute("aria-hidden") === "true") return false;
  const tag = element.tagName.toLowerCase();
  if (tag === "input") {
    const type = (element as HTMLInputElement).type?.toLowerCase() ?? "text";
    if (type === "hidden") return false;
  }
  return true;
}

/**
 * Has the page locked this control?
 *
 * `readonly` is an *attribute*, not a type, so it cannot live in
 * `NEVER_READ_TYPES` - hence a predicate of its own. It applies to text-entry
 * controls only: on a checkbox or a select the attribute means nothing.
 *
 * Two things follow, and both are deliberate:
 *   * the control is still **reported** (the panel has to be able to say why it
 *     is being left alone) but its **value is never read** - a locked box holds
 *     page-managed text, and a value that can neither be reviewed nor edited is
 *     not ours to push across the loopback boundary;
 *   * `writeOne` refuses it. That is the second line of defence: the server
 *     marks it not-fillable so no Apply button appears, and this holds even if a
 *     caller ignores `fillable`.
 */
function isReadonlyControl(element: HTMLElement): boolean {
  const tag = element.tagName.toLowerCase();
  if (tag !== "input" && tag !== "textarea") return false;
  if (element.hasAttribute("readonly")) return true;
  return (element as HTMLInputElement).readOnly === true;
}

/**
 * Has the page switched this control off?
 *
 * Deliberately the same shape as `isReadonlyControl`, because it is the same
 * decision one step further out: the control is still *reported* (the panel has
 * to be able to say why it is left alone), its value is never read, and
 * `writeOne` refuses it.
 *
 * `disabled` is valid on a `<select>` and a `<textarea>` as well as an `<input>`,
 * so this predicate is one tag wider than the readonly one. It is an attribute
 * and not a type, so it cannot live in `NEVER_READ_TYPES`.
 *
 * The server refuses the same controls through
 * `server/field_map.SKIPPED_ATTRIBUTES["disabled"]`, which is the first line of
 * defence; this one holds even if a caller ignores `fillable`. Round 3,
 * report.md section 6.
 */
function isDisabledControl(element: HTMLElement): boolean {
  const tag = element.tagName.toLowerCase();
  if (tag !== "input" && tag !== "textarea" && tag !== "select") return false;
  if (element.hasAttribute("disabled")) return true;
  return (element as HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement).disabled === true;
}

function textOf(element: Element | null | undefined): string {
  return (element?.textContent ?? "").replace(/\s+/g, " ").trim();
}

/**
 * Is this element a *section* label rather than a field label?
 *
 * A `<legend>` names the group it opens; a heading or a `<caption>` names the
 * block. All three are text-only leaves, so the nearby-text rule in
 * `resolveLabel` would otherwise accept them and a control whose only nearby
 * text is a section heading would be named after the section.
 *
 * This is the same mistake as the help-text one (see `resolveHelpText`), found
 * on the `label` side. Measured on form_03: a bare `<textarea>` inside
 * `<legend>Additional information</legend>` came back labelled "Additional
 * information" and was classified as a narrative field it never was.
 *
 * Section text is still available to the server as **context**
 * (`RawField.section_context`), where it can veto the ambiguous `name`
 * fallback. It just cannot be a field's name.
 */
function isSectionLevelText(element: Element): boolean {
  const tag = element.tagName.toLowerCase();
  if (tag === "legend" || tag === "caption") return true;
  if (/^h[1-6]$/.test(tag)) return true;
  return element.getAttribute("role") === "heading";
}

/** The text a human would call this field's name. */
function resolveLabel(element: HTMLElement): string {
  const id = element.getAttribute("id");
  if (id) {
    const explicit = document.querySelector(`label[for="${CSS.escape(id)}"]`);
    const text = textOf(explicit);
    if (text) return text.slice(0, MAX_LABEL_CHARS);
  }
  const aria = element.getAttribute("aria-label");
  if (aria?.trim()) return aria.trim().slice(0, MAX_LABEL_CHARS);

  const labelledBy = element.getAttribute("aria-labelledby");
  if (labelledBy) {
    const parts = labelledBy
      .split(/\s+/)
      .map((token) => textOf(document.getElementById(token)))
      .filter(Boolean);
    if (parts.length) return parts.join(" ").slice(0, MAX_LABEL_CHARS);
  }

  const wrapping = element.closest("label");
  if (wrapping) {
    // Strip the control's own text out of the label so a select's options do not
    // become its name.
    const clone = wrapping.cloneNode(true) as HTMLElement;
    clone.querySelectorAll("input, select, textarea, button").forEach((node) => node.remove());
    const text = textOf(clone);
    if (text) return text.slice(0, MAX_LABEL_CHARS);
  }

  // Nearby text: a short text node sitting directly before the control.
  //
  // Only a *leaf* element counts. Taking any previous sibling wholesale made the
  // preceding `<section>` into the submit button's name, which came out as
  // "Attachments Upload CV Set a password for your applicant portal" - a label
  // stitched together from three unrelated controls. A container with element
  // children is a block of the form, not the name of one field.
  let node: Element | null = element;
  for (let depth = 0; depth < LABEL_ANCESTOR_DEPTH && node; depth += 1) {
    let sibling = node.previousElementSibling;
    while (sibling) {
      if (sibling.childElementCount === 0 && !isSectionLevelText(sibling)) {
        const text = textOf(sibling);
        if (text && text.length <= MAX_LABEL_CHARS) return text;
      }
      sibling = sibling.previousElementSibling;
    }
    node = node.parentElement;
  }
  return "";
}

function resolveHelpText(element: HTMLElement): string {
  const describedBy = element.getAttribute("aria-describedby");
  if (describedBy) {
    const parts = describedBy
      .split(/\s+/)
      .map((token) => textOf(document.getElementById(token)))
      .filter(Boolean);
    if (parts.length) return parts.join(" ").slice(0, MAX_HELP_CHARS);
  }
  // A <fieldset><legend> is deliberately NOT used here. It describes the section,
  // not the field, and the server classifies a field by its label plus its help
  // text - so a section heading leaked into every field inside it. The concrete
  // failure: a field labelled "Why do you want this role?" inside a section called
  // "Skills and motivation" matched the skills pattern on the word "skills" (or
  // "motivation"), was classified as a skills field, and the assistant proposed
  // the candidate's skill list as the answer to a free-text motivation question.
  const title = element.getAttribute("title") ?? "";
  if (title.trim()) return title.trim().slice(0, MAX_HELP_CHARS);
  // A short hint directly after the control is commonly a format note.
  const next = element.nextElementSibling;
  const nextText = next && !next.matches("input,select,textarea,button") ? textOf(next) : "";
  if (nextText && nextText.length <= MAX_HELP_CHARS) return nextText;
  return "";
}

/**
 * The text of the section this control sits in.
 *
 * Recorded as **context, never as a name** - see `isSectionLevelText`. The
 * server uses it for one thing only: to veto the generic `\bname\b` fallback.
 * A control labelled "Name" inside a section called "Employer details" is not
 * the candidate's own name, and the section it sits in is the only evidence for
 * that.
 */
function resolveSectionContext(element: HTMLElement): string {
  const fieldset = element.closest("fieldset");
  const legendText = fieldset ? textOf(fieldset.querySelector("legend")) : "";
  if (legendText) return legendText.slice(0, MAX_LABEL_CHARS);
  let node: Element | null = element.parentElement;
  for (let depth = 0; depth < LABEL_ANCESTOR_DEPTH && node; depth += 1) {
    let sibling = node.previousElementSibling;
    while (sibling) {
      const tag = sibling.tagName.toLowerCase();
      if (/^h[1-6]$/.test(tag) || sibling.getAttribute("role") === "heading") {
        const text = textOf(sibling);
        if (text) return text.slice(0, MAX_LABEL_CHARS);
      }
      sibling = sibling.previousElementSibling;
    }
    node = node.parentElement;
  }
  return "";
}

function resolveOptions(element: HTMLElement): string[] {
  const tag = element.tagName.toLowerCase();
  if (tag === "select") {
    return [...(element as HTMLSelectElement).options]
      .map((option) => option.textContent?.trim() ?? "")
      .filter(Boolean)
      .slice(0, MAX_OPTIONS);
  }
  const type = (element as HTMLInputElement).type?.toLowerCase();
  if (type === "radio" || type === "checkbox") {
    const name = element.getAttribute("name");
    if (!name) {
      const own = resolveLabel(element);
      return own ? [own] : [];
    }
    const group = document.querySelectorAll<HTMLInputElement>(
      `input[type="${type}"][name="${CSS.escape(name)}"]`,
    );
    return [...group]
      .map((item) => resolveLabel(item) || item.value)
      .filter(Boolean)
      .slice(0, MAX_OPTIONS);
  }
  return [];
}

/**
 * A CSS path that resolves back to this element.
 *
 * `field_id` is the identity used for the round trip, so this is a *secondary*
 * handle: it is what the panel shows the user and what a re-scan can fall back
 * on if the DOM has been re-rendered in between.
 */
function buildSelector(element: HTMLElement): string {
  const id = element.getAttribute("id");
  if (id && !/^\d/.test(id)) {
    const candidate = `#${CSS.escape(id)}`;
    if (document.querySelectorAll(candidate).length === 1) return candidate;
  }
  const name = element.getAttribute("name");
  const tag = element.tagName.toLowerCase();
  if (name) {
    const candidate = `${tag}[name="${CSS.escape(name)}"]`;
    if (document.querySelectorAll(candidate).length === 1) return candidate;
  }
  const parts: string[] = [];
  let node: Element | null = element;
  let depth = 0;
  while (node && node !== document.documentElement && depth < 6) {
    const parent: Element | null = node.parentElement;
    if (!parent) break;
    const index = [...parent.children].indexOf(node) + 1;
    parts.unshift(`${node.tagName.toLowerCase()}:nth-child(${index})`);
    node = parent;
    depth += 1;
  }
  return parts.length ? parts.join(" > ") : tag;
}

/**
 * Controls whose current value must never be read.
 *
 * A password box holds a secret and a file input holds a browser-managed fake
 * path. Neither is ever filled by this script - the server refuses both, for the
 * same reason - so reading them would push a secret across the loopback HTTP
 * boundary for no benefit whatsoever. The control itself is still reported, so
 * the panel can explain why it is being left alone; only the value is withheld.
 *
 * Measured, not assumed: before this list existed, a password typed into the
 * demo page came back as `current_value` in the scan result.
 */
const NEVER_READ_TYPES = new Set(["password", "file"]);

function currentValueOf(element: HTMLElement): string {
  const tag = element.tagName.toLowerCase();
  if (tag === "select" || tag === "textarea") {
    return (element as HTMLInputElement | HTMLSelectElement).value ?? "";
  }
  if (tag === "input") {
    const input = element as HTMLInputElement;
    const type = input.type?.toLowerCase();
    if (type === "radio" || type === "checkbox") return input.checked ? input.value || "checked" : "";
    return input.value ?? "";
  }
  return element.textContent ?? "";
}

async function scanPage(): Promise<ScanPageResult> {
  elementMap.clear();
  const selector =
    'input, textarea, select, [contenteditable="true"], [contenteditable=""], [role="textbox"]';
  const seen = new Set<Element>();
  const raw: RawField[] = [];
  const usedIds = new Map<string, number>();

  for (const element of Array.from(document.querySelectorAll(selector))) {
    if (raw.length >= MAX_FIELDS) break;
    if (seen.has(element) || !isFillableControl(element)) continue;
    seen.add(element);

    const html = element as HTMLInputElement;
    const tag = element.tagName.toLowerCase();
    const isContentEditable = element.getAttribute("contenteditable") === "true" ||
      element.getAttribute("contenteditable") === "" ||
      (element.getAttribute("role") === "textbox" && tag !== "input" && tag !== "textarea");
    const controlType = isContentEditable ? "text" : (html.type ?? "text").toLowerCase();

    const field: RawField = {
      tag: isContentEditable ? "contenteditable" : tag,
      type: controlType,
      name: element.getAttribute("name") ?? "",
      id: element.getAttribute("id") ?? "",
      label: resolveLabel(element),
      placeholder: element.getAttribute("placeholder") ?? "",
      aria_label: element.getAttribute("aria-label") ?? "",
      required: element.hasAttribute("required") || element.getAttribute("aria-required") === "true",
      max_length: (() => {
        const raw = element.getAttribute("maxlength");
        const parsed = raw ? Number.parseInt(raw, 10) : Number.NaN;
        return Number.isFinite(parsed) && parsed > 0 ? parsed : null;
      })(),
      options: resolveOptions(element),
      help_text: resolveHelpText(element),
      // Three reasons a value is never read: the control is a secret by type
      // (password / file), the page has locked it, or the page has switched it
      // off. The control is still reported either way - only the value is
      // withheld.
      current_value:
        NEVER_READ_TYPES.has(controlType) || isReadonlyControl(element) || isDisabledControl(element)
          ? ""
          : currentValueOf(element).slice(0, 2000),
      selector: buildSelector(element),
      readonly: isReadonlyControl(element),
      disabled: isDisabledControl(element),
      section_context: resolveSectionContext(element),
    };

    const index = raw.length;
    let fieldId = await computeFieldId(field, index);
    const seenCount = usedIds.get(fieldId) ?? 0;
    usedIds.set(fieldId, seenCount + 1);
    if (seenCount > 0) fieldId = `${fieldId}-${seenCount + 1}`;
    field.field_id = fieldId;

    elementMap.set(fieldId, element);
    raw.push(field);
  }

  return {
    ok: true,
    url: location.href,
    pageTitle: document.title ?? "",
    fields: raw,
  };
}

/* -------------------------------------------------------------- writing */

/**
 * React (and Vue) install a value tracker on inputs; assigning `element.value`
 * directly updates the DOM but leaves the framework's state stale, so the next
 * keystroke or validation pass wipes it. Going through the prototype's own
 * setter is the documented way to defeat that, and dispatching the events is
 * what makes the page's own handlers run.
 */
function setNativeValue(element: HTMLElement, value: string): void {
  const tag = element.tagName.toLowerCase();
  const prototype = tag === "textarea"
    ? HTMLTextAreaElement.prototype
    : tag === "select"
      ? HTMLSelectElement.prototype
      : HTMLInputElement.prototype;
  const descriptor = Object.getOwnPropertyDescriptor(prototype, "value");
  if (descriptor?.set) {
    descriptor.set.call(element, value);
  } else {
    (element as HTMLInputElement).value = value;
  }
}

function dispatchInputEvents(element: HTMLElement): void {
  element.dispatchEvent(new Event("input", { bubbles: true }));
  element.dispatchEvent(new Event("change", { bubbles: true }));
  // A blur is what makes many validation libraries re-check the field.
  element.dispatchEvent(new Event("blur", { bubbles: true }));
}

/* ---------------------------------------------------------- fill feedback */

/**
 * The class a control gets for a moment after the assistant writes into it.
 *
 * Applied as a class rather than an inline style so the page's own CSS still
 * wins where it matters, and injected as a stylesheet so the whole effect is one
 * class to add and one to remove. The outline is drawn *around* the control, so
 * a filled box simply looks filled - nothing about the page's own appearance is
 * restyled, because a content script restyling someone's form is not a change
 * anyone asked for.
 */
const FILL_HIGHLIGHT_CLASS = "rjd-highlight";
const FILL_HIGHLIGHT_STYLE_ID = "rjd-highlight-style";
/** Long enough to catch the eye on a long form, short enough not to linger. */
const FILL_HIGHLIGHT_MS = 600;

const FILL_HIGHLIGHT_CSS =
  `.${FILL_HIGHLIGHT_CLASS}{outline:2px solid #4caf50 !important;` +
  "outline-offset:2px !important;transition:outline-color .2s ease-out;}";

function ensureFillHighlightStyle(): void {
  if (document.getElementById(FILL_HIGHLIGHT_STYLE_ID)) return;
  const style = document.createElement("style");
  style.id = FILL_HIGHLIGHT_STYLE_ID;
  style.textContent = FILL_HIGHLIGHT_CSS;
  (document.head ?? document.documentElement).appendChild(style);
}

/** Mark a control as just written, and take the mark off again. */
function markFilled(element: HTMLElement): void {
  ensureFillHighlightStyle();
  element.classList.add(FILL_HIGHLIGHT_CLASS);
  window.setTimeout(() => element.classList.remove(FILL_HIGHLIGHT_CLASS), FILL_HIGHLIGHT_MS);
}

function resolveElement(fieldId: string): HTMLElement | null {
  const known = elementMap.get(fieldId);
  if (known && known.isConnected) return known;
  return null;
}

function writeOne(fieldId: string, text: string): FillFieldResult {
  const element = resolveElement(fieldId);
  if (!element) {
    return {
      field_id: fieldId,
      ok: false,
      fallback: true,
      reason: "the field is no longer on the page (it may have been re-rendered); copy and paste instead",
    };
  }

  const tag = element.tagName.toLowerCase();
  const isContentEditable =
    element.getAttribute("contenteditable") === "true" ||
    element.getAttribute("contenteditable") === "" ||
    (element.getAttribute("role") === "textbox" && tag !== "input" && tag !== "textarea");

  // Second line of defence for the two page-side locks (the first is the
  // server's not-fillable flag). A page-side refusal costs nothing and still
  // holds if a caller ignores `fillable`.
  if (isReadonlyControl(element)) {
    return {
      field_id: fieldId,
      ok: false,
      fallback: true,
      reason:
        "this control is readonly, so a value written here could not be edited or confirmed; copy and paste instead",
    };
  }

  if (isDisabledControl(element)) {
    return {
      field_id: fieldId,
      ok: false,
      fallback: true,
      reason:
        "this control is disabled, so it cannot be typed into and the page would not submit it; copy and paste instead",
    };
  }

  try {
    if (tag === "select") {
      const select = element as HTMLSelectElement;
      const option = [...select.options].find(
        (item) => item.textContent?.trim() === text || item.value === text,
      );
      if (!option) {
        return {
          field_id: fieldId,
          ok: false,
          fallback: true,
          reason: `this control has no option matching "${text}"`,
        };
      }
      select.value = option.value;
      dispatchInputEvents(element);
    } else if (isContentEditable) {
      element.focus();
      element.textContent = text;
      element.dispatchEvent(new Event("input", { bubbles: true }));
      element.dispatchEvent(new Event("blur", { bubbles: true }));
    } else if (tag === "input" && ["radio", "checkbox"].includes((element as HTMLInputElement).type)) {
      const input = element as HTMLInputElement;
      // The only click this script ever performs is on a radio or checkbox.
      const label = resolveLabel(input);
      const matches = input.value === text || label === text || label.includes(text);
      if (!matches) {
        return {
          field_id: fieldId,
          ok: false,
          fallback: true,
          reason: `"${text}" does not match this option (${label || input.value})`,
        };
      }
      if (!input.checked) input.click();
      dispatchInputEvents(input);
    } else {
      const maxLength = (element as HTMLInputElement).maxLength;
      const value = maxLength && maxLength > 0 ? text.slice(0, maxLength) : text;
      element.focus();
      setNativeValue(element, value);
      dispatchInputEvents(element);
    }
  } catch (error) {
    return {
      field_id: fieldId,
      ok: false,
      fallback: true,
      reason: `the write failed: ${(error as Error).message}`,
    };
  }

  const after = currentValueOf(element);
  const expected = text;
  if (!isContentEditable && tag !== "select" && after !== expected && !after.includes(expected.slice(0, 20))) {
    return {
      field_id: fieldId,
      ok: false,
      fallback: true,
      reason: "the page rejected the value (its own script may have cleared it); copy and paste instead",
    };
  }
  // The write landed, so mark the control for a moment: the panel says
  // "filled", and this is the page saying *where*. On a form with forty
  // controls that is the difference between knowing and guessing.
  markFilled(element);
  return { field_id: fieldId, ok: true, fallback: false, reason: "" };
}

function fillFields(request: FillFieldsRequest): FillFieldsResult {
  const results: FillFieldResult[] = [];
  for (const [fieldId, text] of Object.entries(request.values ?? {})) {
    results.push(writeOne(fieldId, text));
  }
  return { ok: results.every((result) => result.ok), results };
}

function highlightField(request: HighlightFieldRequest): HighlightFieldResult {
  const element = resolveElement(request.field_id);
  if (!element) return { ok: false, error: "the field is not on the page any more" };
  element.scrollIntoView({ behavior: "smooth", block: "center" });
  const previous = element.style.outline;
  element.style.outline = "2px solid #d9480f";
  element.style.outlineOffset = "2px";
  window.setTimeout(() => {
    element.style.outline = previous;
    element.style.outlineOffset = "";
  }, 2200);
  return { ok: true };
}

/* ---------------------------------------------------------------- wiring */

chrome.runtime.onMessage.addListener(
  (message: ContentRequest, _sender, sendResponse: (response: unknown) => void) => {
    (async () => {
      switch (message?.type) {
        case "RJD_SCAN_PAGE":
          sendResponse(await scanPage());
          return;
        case "RJD_FILL_FIELDS":
          sendResponse(fillFields(message));
          return;
        case "RJD_HIGHLIGHT_FIELD":
          sendResponse(highlightField(message));
          return;
        default:
          sendResponse({ ok: false, error: `unknown request ${String((message as { type?: string })?.type)}` });
      }
    })().catch((error: unknown) => {
      sendResponse({ ok: false, error: (error as Error).message ?? "content script error" });
    });
    // Asynchronous response.
    return true;
  },
);
