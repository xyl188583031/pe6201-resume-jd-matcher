/**
 * `useLabel()` - the one way a component asks for a string.
 *
 * The signature the panel uses is deliberately small:
 *
 *     const { label, language, setLanguage } = useLabel();
 *     <button>{label("scan")}</button>
 *
 * The state lives in a module-level store rather than in a React context. The
 * reason is the language control: it is mounted once, at the top of the tree,
 * while the strings it changes are rendered by seven sibling components. With
 * per-component `useState`, clicking the control would re-render the control
 * and nothing else. A context would fix that but would also add a provider that
 * every future component has to be inside - and `useLabel()` is called from
 * components that are sometimes rendered in isolation. `useSyncExternalStore`
 * over a module singleton keeps the call signature context-free and still gives
 * every subscriber the same value in the same render pass.
 *
 * Reading storage is deferred and happens exactly once per document:
 *
 * * the first render returns `DEFAULT_LANGUAGE`, so the panel paints
 *   immediately rather than flashing empty while `chrome.storage` is read;
 * * the read then corrects the value if the user has chosen something else;
 * * a failed read (or a failed write) leaves the last known value in place
 *   instead of throwing at the user.
 */

import { useCallback, useEffect, useSyncExternalStore } from "react";

import { DEFAULT_LANGUAGE, getLanguage, setLanguage, type Language } from "../../storage";

import { labels, lookupLabel, renderLabel, type Label } from "../labels";

/* ------------------------------------------------------------- the store */

let current: Language = DEFAULT_LANGUAGE;
let hydration: Promise<void> | null = null;

const listeners = new Set<() => void>();

function emit(): void {
  for (const listener of Array.from(listeners)) listener();
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

function snapshot(): Language {
  return current;
}

/**
 * Keep the document itself in step with the panel.
 *
 * `document.title` and `<html lang>` are part of the page the user is looking
 * at, so a panel that says "English" while its own tab title is Chinese is not
 * actually switched. The title is not part of the rendered body, which is why
 * it has to be set here rather than in a component.
 */
function applyDocumentLanguage(language: Language): void {
  if (typeof document === "undefined") return;
  document.documentElement.lang = language === "en" ? "en" : "zh-CN";
  document.title = renderLabel(labels.appTitle, language);
}

/** Read the stored preference once per document. */
function hydrate(): Promise<void> {
  if (!hydration) {
    hydration = getLanguage()
      .catch(() => DEFAULT_LANGUAGE)
      .then((language) => {
        applyDocumentLanguage(language);
        if (language !== current) {
          current = language;
          emit();
        }
      });
  }
  return hydration;
}

/** Change the language: update every subscriber now, persist in the background. */
function apply(language: Language): void {
  current = language;
  applyDocumentLanguage(language);
  emit();
  // Not awaited: the UI must not wait on storage to repaint. A write that fails
  // leaves the session on the new language and reverts at the next reload.
  void setLanguage(language).catch(() => undefined);
}

/* -------------------------------------------------------------- the hook */

export interface UseLabel {
  /** Resolve a key to the string for the current language. Unknown keys pass through. */
  label: (key: string) => string;
  language: Language;
  setLanguage: (language: Language) => void;
}

export function useLabel(): UseLabel {
  const language = useSyncExternalStore(subscribe, snapshot, snapshot);

  useEffect(() => {
    void hydrate();
  }, []);

  const label = useCallback(
    (key: string): string => {
      const entry: Label | undefined = lookupLabel(key);
      return entry ? renderLabel(entry, language) : key;
    },
    [language],
  );

  return { label, language, setLanguage: apply };
}
