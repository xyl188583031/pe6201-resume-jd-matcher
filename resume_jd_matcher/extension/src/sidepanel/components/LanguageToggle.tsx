import { useLabel } from "../hooks/useLabel";

/**
 * The three-way language switch.
 *
 * Captions are ASCII language tags ("ZH" / "EN" / "ZH+EN") rather than the
 * Chinese endonyms the brief sketched. The reason is not aesthetic: the browser
 * check asserts that the panel contains no CJK characters in English mode, and a
 * switcher drawn with the Chinese glyphs would put two of them on screen
 * permanently - which would force the check to carve out an exception for
 * exactly the control the check exists to prove. The readable names are still
 * there, on `aria-label` and `title`, and those *are* translated.
 *
 * This component takes no props and holds no state of its own: it reads the
 * shared language store and writes back to it, so it cannot get out of step
 * with the labels it switches.
 */
export default function LanguageToggle() {
  const { language, setLanguage, label } = useLabel();

  return (
    <div
      className="language-toggle"
      role="group"
      aria-label={label("language")}
      data-testid="language-toggle"
    >
      <button
        type="button"
        onClick={() => setLanguage("zh")}
        aria-pressed={language === "zh"}
        aria-label={label("langZh")}
        title={label("langZh")}
        className={language === "zh" ? "active" : ""}
        data-testid="language-zh"
      >
        ZH
      </button>
      <button
        type="button"
        onClick={() => setLanguage("en")}
        aria-pressed={language === "en"}
        aria-label={label("langEn")}
        title={label("langEn")}
        className={language === "en" ? "active" : ""}
        data-testid="language-en"
      >
        EN
      </button>
      <button
        type="button"
        onClick={() => setLanguage("bilingual")}
        aria-pressed={language === "bilingual"}
        aria-label={label("langBilingual")}
        title={label("langBilingual")}
        className={language === "bilingual" ? "active" : ""}
        data-testid="language-bilingual"
      >
        ZH+EN
      </button>
    </div>
  );
}
