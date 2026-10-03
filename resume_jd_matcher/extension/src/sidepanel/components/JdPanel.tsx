import type { JdFetchResponse } from "../../types";
import { useLabel } from "../hooks/useLabel";

interface Props {
  jdText: string;
  jdUrl: string;
  onTextChange: (value: string) => void;
  onUrlChange: (value: string) => void;
  onPersist: () => void;
  onFetch: () => void;
  fetching: boolean;
  /** Last successful fetch, used to show title + char count. */
  fetched: JdFetchResponse | null;
  /** Last fetch failure; rendered verbatim so the user can paste manually. */
  fetchError: string | null;
}

export default function JdPanel({
  jdText,
  jdUrl,
  onTextChange,
  onUrlChange,
  onPersist,
  onFetch,
  fetching,
  fetched,
  fetchError,
}: Props) {
  const { label } = useLabel();

  return (
    <section className="section" aria-label={label("jd")} data-testid="jd-panel">
      <h2>{label("jd")}</h2>
      <p className="note">{label("jdNote")}</p>

      <label htmlFor="jd-text">{label("jdPaste")}</label>
      <textarea
        id="jd-text"
        rows={5}
        value={jdText}
        onChange={(e) => onTextChange(e.target.value)}
        onBlur={onPersist}
      />

      <label htmlFor="jd-url">{label("jdUrl")}</label>
      <div style={{ display: "flex", gap: 6 }}>
        <input
          id="jd-url"
          type="url"
          value={jdUrl}
          onChange={(e) => onUrlChange(e.target.value)}
          onBlur={onPersist}
        />
        <button type="button" onClick={onFetch} disabled={fetching || jdUrl.trim() === ""}>
          {fetching ? label("fetching") : label("fetch")}
        </button>
      </div>

      {fetched && (
        <p className="note">
          {label("fetchedTitle")}: {fetched.title || label("none")} — {fetched.chars}{" "}
          {label("chars")}
        </p>
      )}

      {fetchError && (
        // Render the server's message verbatim; never silently fall back to paste.
        <div className="fallback-reason" role="alert">
          {fetchError}
        </div>
      )}
    </section>
  );
}
