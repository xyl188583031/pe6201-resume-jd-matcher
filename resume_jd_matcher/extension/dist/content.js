const MAX_FIELDS = 400;
const MAX_HELP_CHARS = 180;
const MAX_OPTIONS = 40;
const MAX_LABEL_CHARS = 200;
const LABEL_ANCESTOR_DEPTH = 4;
async function computeFieldId(field, index) {
  const basis = [field.name, field.id, field.label, field.placeholder].map((part) => (part ?? "").trim()).join("|");
  if (!basis.replace(/\|/g, "").trim()) {
    return `wf_anon_${String(index).padStart(3, "0")}`;
  }
  const digest = await sha1Hex(basis);
  return `wf_${digest.slice(0, 12)}`;
}
async function sha1Hex(text) {
  const bytes = new TextEncoder().encode(text);
  if (globalThis.crypto?.subtle) {
    const buffer = await globalThis.crypto.subtle.digest("SHA-1", bytes);
    return [...new Uint8Array(buffer)].map((b) => b.toString(16).padStart(2, "0")).join("");
  }
  let h1 = 2166136261;
  let h2 = 16777619;
  for (const byte of bytes) {
    h1 = (h1 ^ byte) >>> 0;
    h1 = h1 * 16777619 >>> 0;
    h2 = h2 + byte * 31 >>> 0;
  }
  return (h1.toString(16).padStart(8, "0") + h2.toString(16).padStart(8, "0")).repeat(2).slice(0, 40);
}
const elementMap = /* @__PURE__ */ new Map();
function isFillableControl(element) {
  if (!(element instanceof HTMLElement)) return false;
  if (element.hidden) return false;
  if (element.getAttribute("aria-hidden") === "true") return false;
  const tag = element.tagName.toLowerCase();
  if (tag === "input") {
    const type = element.type?.toLowerCase() ?? "text";
    if (type === "hidden") return false;
  }
  return true;
}
function isReadonlyControl(element) {
  const tag = element.tagName.toLowerCase();
  if (tag !== "input" && tag !== "textarea") return false;
  if (element.hasAttribute("readonly")) return true;
  return element.readOnly === true;
}
function isDisabledControl(element) {
  const tag = element.tagName.toLowerCase();
  if (tag !== "input" && tag !== "textarea" && tag !== "select") return false;
  if (element.hasAttribute("disabled")) return true;
  return element.disabled === true;
}
function textOf(element) {
  return (element?.textContent ?? "").replace(/\s+/g, " ").trim();
}
function isSectionLevelText(element) {
  const tag = element.tagName.toLowerCase();
  if (tag === "legend" || tag === "caption") return true;
  if (/^h[1-6]$/.test(tag)) return true;
  return element.getAttribute("role") === "heading";
}
function resolveLabel(element) {
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
    const parts = labelledBy.split(/\s+/).map((token) => textOf(document.getElementById(token))).filter(Boolean);
    if (parts.length) return parts.join(" ").slice(0, MAX_LABEL_CHARS);
  }
  const wrapping = element.closest("label");
  if (wrapping) {
    const clone = wrapping.cloneNode(true);
    clone.querySelectorAll("input, select, textarea, button").forEach((node2) => node2.remove());
    const text = textOf(clone);
    if (text) return text.slice(0, MAX_LABEL_CHARS);
  }
  let node = element;
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
function resolveHelpText(element) {
  const describedBy = element.getAttribute("aria-describedby");
  if (describedBy) {
    const parts = describedBy.split(/\s+/).map((token) => textOf(document.getElementById(token))).filter(Boolean);
    if (parts.length) return parts.join(" ").slice(0, MAX_HELP_CHARS);
  }
  const title = element.getAttribute("title") ?? "";
  if (title.trim()) return title.trim().slice(0, MAX_HELP_CHARS);
  const next = element.nextElementSibling;
  const nextText = next && !next.matches("input,select,textarea,button") ? textOf(next) : "";
  if (nextText && nextText.length <= MAX_HELP_CHARS) return nextText;
  return "";
}
function resolveSectionContext(element) {
  const fieldset = element.closest("fieldset");
  const legendText = fieldset ? textOf(fieldset.querySelector("legend")) : "";
  if (legendText) return legendText.slice(0, MAX_LABEL_CHARS);
  let node = element.parentElement;
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
function resolveOptions(element) {
  const tag = element.tagName.toLowerCase();
  if (tag === "select") {
    return [...element.options].map((option) => option.textContent?.trim() ?? "").filter(Boolean).slice(0, MAX_OPTIONS);
  }
  const type = element.type?.toLowerCase();
  if (type === "radio" || type === "checkbox") {
    const name = element.getAttribute("name");
    if (!name) {
      const own = resolveLabel(element);
      return own ? [own] : [];
    }
    const group = document.querySelectorAll(
      `input[type="${type}"][name="${CSS.escape(name)}"]`
    );
    return [...group].map((item) => resolveLabel(item) || item.value).filter(Boolean).slice(0, MAX_OPTIONS);
  }
  return [];
}
function buildSelector(element) {
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
  const parts = [];
  let node = element;
  let depth = 0;
  while (node && node !== document.documentElement && depth < 6) {
    const parent = node.parentElement;
    if (!parent) break;
    const index = [...parent.children].indexOf(node) + 1;
    parts.unshift(`${node.tagName.toLowerCase()}:nth-child(${index})`);
    node = parent;
    depth += 1;
  }
  return parts.length ? parts.join(" > ") : tag;
}
const NEVER_READ_TYPES = /* @__PURE__ */ new Set(["password", "file"]);
function currentValueOf(element) {
  const tag = element.tagName.toLowerCase();
  if (tag === "select" || tag === "textarea") {
    return element.value ?? "";
  }
  if (tag === "input") {
    const input = element;
    const type = input.type?.toLowerCase();
    if (type === "radio" || type === "checkbox") return input.checked ? input.value || "checked" : "";
    return input.value ?? "";
  }
  return element.textContent ?? "";
}
async function scanPage() {
  elementMap.clear();
  const selector = 'input, textarea, select, [contenteditable="true"], [contenteditable=""], [role="textbox"]';
  const seen = /* @__PURE__ */ new Set();
  const raw = [];
  const usedIds = /* @__PURE__ */ new Map();
  for (const element of Array.from(document.querySelectorAll(selector))) {
    if (raw.length >= MAX_FIELDS) break;
    if (seen.has(element) || !isFillableControl(element)) continue;
    seen.add(element);
    const html = element;
    const tag = element.tagName.toLowerCase();
    const isContentEditable = element.getAttribute("contenteditable") === "true" || element.getAttribute("contenteditable") === "" || element.getAttribute("role") === "textbox" && tag !== "input" && tag !== "textarea";
    const controlType = isContentEditable ? "text" : (html.type ?? "text").toLowerCase();
    const field = {
      tag: isContentEditable ? "contenteditable" : tag,
      type: controlType,
      name: element.getAttribute("name") ?? "",
      id: element.getAttribute("id") ?? "",
      label: resolveLabel(element),
      placeholder: element.getAttribute("placeholder") ?? "",
      aria_label: element.getAttribute("aria-label") ?? "",
      required: element.hasAttribute("required") || element.getAttribute("aria-required") === "true",
      max_length: (() => {
        const raw2 = element.getAttribute("maxlength");
        const parsed = raw2 ? Number.parseInt(raw2, 10) : Number.NaN;
        return Number.isFinite(parsed) && parsed > 0 ? parsed : null;
      })(),
      options: resolveOptions(element),
      help_text: resolveHelpText(element),
      // Three reasons a value is never read: the control is a secret by type
      // (password / file), the page has locked it, or the page has switched it
      // off. The control is still reported either way - only the value is
      // withheld.
      current_value: NEVER_READ_TYPES.has(controlType) || isReadonlyControl(element) || isDisabledControl(element) ? "" : currentValueOf(element).slice(0, 2e3),
      selector: buildSelector(element),
      readonly: isReadonlyControl(element),
      disabled: isDisabledControl(element),
      section_context: resolveSectionContext(element)
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
    fields: raw
  };
}
function setNativeValue(element, value) {
  const tag = element.tagName.toLowerCase();
  const prototype = tag === "textarea" ? HTMLTextAreaElement.prototype : tag === "select" ? HTMLSelectElement.prototype : HTMLInputElement.prototype;
  const descriptor = Object.getOwnPropertyDescriptor(prototype, "value");
  if (descriptor?.set) {
    descriptor.set.call(element, value);
  } else {
    element.value = value;
  }
}
function dispatchInputEvents(element) {
  element.dispatchEvent(new Event("input", { bubbles: true }));
  element.dispatchEvent(new Event("change", { bubbles: true }));
  element.dispatchEvent(new Event("blur", { bubbles: true }));
}
const FILL_HIGHLIGHT_CLASS = "rjd-highlight";
const FILL_HIGHLIGHT_STYLE_ID = "rjd-highlight-style";
const FILL_HIGHLIGHT_MS = 600;
const FILL_HIGHLIGHT_CSS = `.${FILL_HIGHLIGHT_CLASS}{outline:2px solid #4caf50 !important;outline-offset:2px !important;transition:outline-color .2s ease-out;}`;
function ensureFillHighlightStyle() {
  if (document.getElementById(FILL_HIGHLIGHT_STYLE_ID)) return;
  const style = document.createElement("style");
  style.id = FILL_HIGHLIGHT_STYLE_ID;
  style.textContent = FILL_HIGHLIGHT_CSS;
  (document.head ?? document.documentElement).appendChild(style);
}
function markFilled(element) {
  ensureFillHighlightStyle();
  element.classList.add(FILL_HIGHLIGHT_CLASS);
  window.setTimeout(() => element.classList.remove(FILL_HIGHLIGHT_CLASS), FILL_HIGHLIGHT_MS);
}
function resolveElement(fieldId) {
  const known = elementMap.get(fieldId);
  if (known && known.isConnected) return known;
  return null;
}
function writeOne(fieldId, text) {
  const element = resolveElement(fieldId);
  if (!element) {
    return {
      field_id: fieldId,
      ok: false,
      fallback: true,
      reason: "the field is no longer on the page (it may have been re-rendered); copy and paste instead"
    };
  }
  const tag = element.tagName.toLowerCase();
  const isContentEditable = element.getAttribute("contenteditable") === "true" || element.getAttribute("contenteditable") === "" || element.getAttribute("role") === "textbox" && tag !== "input" && tag !== "textarea";
  if (isReadonlyControl(element)) {
    return {
      field_id: fieldId,
      ok: false,
      fallback: true,
      reason: "this control is readonly, so a value written here could not be edited or confirmed; copy and paste instead"
    };
  }
  if (isDisabledControl(element)) {
    return {
      field_id: fieldId,
      ok: false,
      fallback: true,
      reason: "this control is disabled, so it cannot be typed into and the page would not submit it; copy and paste instead"
    };
  }
  try {
    if (tag === "select") {
      const select = element;
      const option = [...select.options].find(
        (item) => item.textContent?.trim() === text || item.value === text
      );
      if (!option) {
        return {
          field_id: fieldId,
          ok: false,
          fallback: true,
          reason: `this control has no option matching "${text}"`
        };
      }
      select.value = option.value;
      dispatchInputEvents(element);
    } else if (isContentEditable) {
      element.focus();
      element.textContent = text;
      element.dispatchEvent(new Event("input", { bubbles: true }));
      element.dispatchEvent(new Event("blur", { bubbles: true }));
    } else if (tag === "input" && ["radio", "checkbox"].includes(element.type)) {
      const input = element;
      const label = resolveLabel(input);
      const matches = input.value === text || label === text || label.includes(text);
      if (!matches) {
        return {
          field_id: fieldId,
          ok: false,
          fallback: true,
          reason: `"${text}" does not match this option (${label || input.value})`
        };
      }
      if (!input.checked) input.click();
      dispatchInputEvents(input);
    } else {
      const maxLength = element.maxLength;
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
      reason: `the write failed: ${error.message}`
    };
  }
  const after = currentValueOf(element);
  const expected = text;
  if (!isContentEditable && tag !== "select" && after !== expected && !after.includes(expected.slice(0, 20))) {
    return {
      field_id: fieldId,
      ok: false,
      fallback: true,
      reason: "the page rejected the value (its own script may have cleared it); copy and paste instead"
    };
  }
  markFilled(element);
  return { field_id: fieldId, ok: true, fallback: false, reason: "" };
}
function fillFields(request) {
  const results = [];
  for (const [fieldId, text] of Object.entries(request.values ?? {})) {
    results.push(writeOne(fieldId, text));
  }
  return { ok: results.every((result) => result.ok), results };
}
function highlightField(request) {
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
chrome.runtime.onMessage.addListener(
  (message, _sender, sendResponse) => {
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
          sendResponse({ ok: false, error: `unknown request ${String(message?.type)}` });
      }
    })().catch((error) => {
      sendResponse({ ok: false, error: error.message ?? "content script error" });
    });
    return true;
  }
);
//# sourceMappingURL=content.js.map
