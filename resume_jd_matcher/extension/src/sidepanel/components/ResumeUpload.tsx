import { useRef, useState } from "react";

import type { ExtractResumeResponse } from "../../types";
import { useLabel } from "../hooks/useLabel";
import { PdfTextError, extractPdfText } from "../pdf";

interface Props {
  /** Send extracted text to the background worker, which owns the backend call. */
  onExtract: (text: string) => Promise<ExtractResumeResponse | null>;
  /** Write a confirmed profile into the one profile slot the panel has. */
  onApply: (response: ExtractResumeResponse) => void;
  /** True when the profile currently in the panel came from an upload. */
  applied: boolean;
}

/**
 * What the drop zone is doing, as one value rather than four booleans.
 *
 * The four states are mutually exclusive, and collapsing them is what keeps
 * "parsing" and "extracting" from being shown at the same time.
 */
type Stage = "idle" | "parsing" | "extracting" | "ready";

/**
 * Upload a resume, read it in the browser, and offer the result for review.
 *
 * The component deliberately stops at *offering*: it never writes the profile
 * itself. Applying is a separate step the user takes, because an upload that
 * silently replaced a profile someone had typed in by hand would be destructive
 * and, worse, silent about it.
 *
 * The PDF is parsed here and nowhere else. Only the text goes to `onExtract`,
 * which is the panel's single channel to the background worker - so the file
 * never crosses the loopback boundary, and there is nothing in the backend to
 * accept one.
 */
export default function ResumeUpload({ onExtract, onApply, applied }: Props) {
  const { label } = useLabel();
  const inputRef = useRef<HTMLInputElement | null>(null);

  const [stage, setStage] = useState<Stage>("idle");
  const [dragging, setDragging] = useState(false);
  const [fileName, setFileName] = useState("");
  const [result, setResult] = useState<ExtractResumeResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function consume(chosen: File | null | undefined): Promise<void> {
    if (!chosen) return;
    setError(null);
    setResult(null);
    setFileName(chosen.name);
    setStage("parsing");

    let text: string;
    try {
      text = await extractPdfText(chosen);
    } catch (e) {
      setStage("idle");
      // A `PdfTextError` carries a label key; anything else is unexpected and is
      // shown as-is rather than dressed up as a known condition.
      setError(e instanceof PdfTextError ? label(e.key) : String(e));
      return;
    }

    if (!text.trim()) {
      setStage("idle");
      setError(label("resumeNoText"));
      return;
    }

    setStage("extracting");
    const response = await onExtract(text);
    if (!response) {
      // `onExtract` has already put the reason on the panel's error banner; this
      // component only has to stop claiming to be busy.
      setStage("idle");
      return;
    }
    setResult(response);
    setStage("ready");
  }

  const busy = stage === "parsing" || stage === "extracting";
  const caption =
    stage === "parsing"
      ? label("resumeParsing")
      : stage === "extracting"
        ? label("resumeExtracting")
        : label("resumeChoose");

  return (
    <section className="section" aria-label={label("resumeTitle")} data-testid="resume-section">
      <h2>{label("resumeTitle")}</h2>
      <p className="note">{label("resumeHint")}</p>

      <div
        className={`resume-drop${dragging ? " over" : ""}${busy ? " busy" : ""}`}
        data-testid="resume-dropzone"
        role="button"
        tabIndex={0}
        aria-busy={busy}
        aria-label={label("resumeChoose")}
        onClick={(event) => {
          // The hidden input lives inside the zone, so a click on it bubbles back
          // here. Without this guard `input.click()` would re-enter this handler
          // for ever.
          if (event.target === inputRef.current) return;
          inputRef.current?.click();
        }}
        onKeyDown={(event) => {
          if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            inputRef.current?.click();
          }
        }}
        onDragOver={(event) => {
          event.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(event) => {
          event.preventDefault();
          setDragging(false);
          void consume(event.dataTransfer?.files?.[0]);
        }}
      >
        <div>{caption}</div>
        {fileName && <div className="note clip" title={fileName}>{fileName}</div>}
        <input
          ref={inputRef}
          type="file"
          accept="application/pdf,.pdf"
          data-testid="resume-file-input"
          onChange={(event) => {
            void consume(event.target.files?.[0]);
            // Reset so choosing the same file twice fires `change` again.
            event.target.value = "";
          }}
        />
      </div>

      {error && (
        <div className="offline-warn" role="alert">
          {label("error")}: {error}
        </div>
      )}

      {result && (
        <div className="confirm-list" data-testid="resume-confirm">
          <div className="field-row">
            <span className="field-label">{label("resumeFound")}</span>
            <span
              className="field-value clip"
              title={result.extracted_fields.join(", ")}
            >
              {result.extracted_fields.join(", ") || label("none")}
            </span>
          </div>

          {result.uncertain_fields.length > 0 && (
            <div className="field-row">
              <span className="field-label">{label("resumeUncertain")}</span>
              <span
                className="field-value clip"
                title={result.uncertain_fields.join(", ")}
              >
                {result.uncertain_fields.join(", ")}
              </span>
            </div>
          )}

          <div className="action-row">
            <button
              type="button"
              className="primary small"
              onClick={() => onApply(result)}
              data-testid="resume-apply"
            >
              {label("resumeApply")}
            </button>
          </div>

          {applied && <p className="note">{label("resumeApplied")}</p>}
        </div>
      )}
    </section>
  );
}
