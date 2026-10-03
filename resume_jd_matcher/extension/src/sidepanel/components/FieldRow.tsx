import { useEffect, useState } from "react";
import type { FieldDraft, FieldSuggestion, FillFieldResult } from "../../types";
import { withholdReason } from "../../types";
import { useLabel } from "../hooks/useLabel";

/** Above this many characters the value is edited in a textarea, not an input. */
const LONG_TEXT = 60;

/** Chip states, as keys, so a chip caption is translated like everything else. */
const CHIP_KEYS: Record<string, string> = {
  offered: "chipOffered",
  sensitive_skipped: "chipSensitive",
  missing: "chipMissing",
  declined_low_confidence: "chipDeclined",
  not_fillable: "chipNotFillable",
  already_filled: "chipAlreadyFilled",
};

interface Props {
  field: FieldSuggestion;
  draft: FieldDraft | undefined;
  /** Fallback result from the last fill, if this field could not be written. */
  fillResult: FillFieldResult | undefined;
  onValueChange: (fieldId: string, value: string) => void;
  onConfirmToggle: (fieldId: string) => void;
  onFillOne: (fieldId: string) => void;
  onCopy: (value: string) => void;
  onLocate: (fieldId: string) => void;
  /** For already_filled rows: re-run generation with overwriteFilled. */
  onRegenerateReplace: () => void;
}

export default function FieldRow({
  field,
  draft,
  fillResult,
  onValueChange,
  onConfirmToggle,
  onFillOne,
  onCopy,
  onLocate,
  onRegenerateReplace,
}: Props) {
  const { label } = useLabel();
  const [copied, setCopied] = useState(false);

  // Two fades, both keyed on the *result object* rather than on
  // `fillResult.ok`. `fillResults` is rebuilt on every fill, so a fresh
  // object means a fresh write; a re-render that filled nothing leaves the
  // identity alone and must not re-trigger the flash.
  const [flashing, setFlashing] = useState(false);
  const [checked, setChecked] = useState(false);

  useEffect(() => {
    if (!fillResult?.ok) return;
    setFlashing(true);
    setChecked(true);
    const flash = window.setTimeout(() => setFlashing(false), 800);
    const tick = window.setTimeout(() => setChecked(false), 2000);
    return () => {
      window.clearTimeout(flash);
      window.clearTimeout(tick);
    };
  }, [fillResult]);

  // `already_filled` is shown distinctly (blue) regardless of withholdReason,
  // because the assistant must never silently overwrite the user's own typing.
  const chip = field.already_filled ? "already_filled" : withholdReason(field);
  const value = draft?.value ?? field.current_value ?? "";

  const long = (field.max_length !== null && field.max_length > 200) || value.length > LONG_TEXT;
  const sensitive = chip === "sensitive_skipped";

  // A page can put a paragraph where a label was expected. The cell clips it and
  // the whole string stays reachable on hover, so nothing is lost - only the
  // layout is protected.
  const labelText = field.label || field.field_id;
  const sourceText = field.source || label("none");
  const relevanceText = field.jd_relevance || label("none");

  async function handleCopy() {
    // The value is never a document number here: sensitive rows render no value.
    await onCopy(value);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  }

  return (
    <tr className={flashing ? "row-just-filled" : ""}>
      <td>
        <span className="clip field-label" title={labelText}>
          {labelText}
        </span>
        {draft?.edited && <span className="edited-marker">{label("editedMarker")}</span>}
        {checked && (
          <span
            className="fill-check"
            title={label("fillCheck")}
            data-testid={`fill-check-${field.field_id}`}
          >
            ✓
          </span>
        )}
      </td>

      <td>
        <span className={`chip ${chip}`}>{label(CHIP_KEYS[chip] ?? chip)}</span>
      </td>

      <td>
        {sensitive ? (
          // A sensitive row shows ONLY the warning; never a value box.
          <div className="sensitive-alert" role="alert">
            {field.message || label("sensitiveWarning")}
          </div>
        ) : (
          <>
            {long ? (
              <textarea
                className="field-value"
                rows={3}
                value={value}
                onChange={(e) => onValueChange(field.field_id, e.target.value)}
              />
            ) : (
              <input
                className="field-value"
                type="text"
                value={value}
                onChange={(e) => onValueChange(field.field_id, e.target.value)}
              />
            )}
            {field.already_filled && <p className="note">{label("alreadyFilledNote")}</p>}
          </>
        )}
        {fillResult?.fallback && (
          <div className="fallback-reason" role="alert">
            {fillResult.reason || label("fallbackNote")}
          </div>
        )}
      </td>

      <td>
        <span className="clip" title={sourceText}>
          {sourceText}
        </span>
      </td>
      <td>
        <span className="clip" title={relevanceText}>
          {relevanceText}
        </span>
      </td>
      <td>{field.confidence.toFixed(2)}</td>
      <td>{field.required ? label("yes") : label("no")}</td>
      <td>{field.max_length === null ? "—" : String(field.max_length)}</td>

      <td>
        <div className="row-actions">
          <button
            type="button"
            className={`small ${draft?.confirmed ? "active" : ""}`}
            onClick={() => onConfirmToggle(field.field_id)}
          >
            {draft?.confirmed ? label("confirmed") : label("confirm")}
          </button>
          {!sensitive && (
            <button
              type="button"
              className="small"
              onClick={() => onFillOne(field.field_id)}
              data-testid={`fill-${field.field_id}`}
            >
              {label("fillThis")}
            </button>
          )}
          <button type="button" className="small" onClick={handleCopy}>
            {copied ? label("copied") : label("copy")}
          </button>
          <button type="button" className="small" onClick={() => onLocate(field.field_id)}>
            {label("locate")}
          </button>
          {field.already_filled && (
            <button type="button" className="small" onClick={onRegenerateReplace}>
              {label("regenerateReplace")}
            </button>
          )}
        </div>
      </td>
    </tr>
  );
}
