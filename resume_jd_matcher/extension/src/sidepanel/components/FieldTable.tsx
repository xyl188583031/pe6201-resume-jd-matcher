import type {
  DraftMap,
  FieldDraft,
  FillFieldResult,
  GenerateResponse,
} from "../../types";
import { useLabel } from "../hooks/useLabel";
import FieldRow from "./FieldRow";

interface Props {
  response: GenerateResponse;
  drafts: DraftMap;
  /** Flattened results from the last fill, used to flag fallback rows. */
  fillResults: FillFieldResult[];
  fillingAll: boolean;
  onValueChange: (fieldId: string, value: string) => void;
  onConfirmToggle: (fieldId: string) => void;
  onFillOne: (fieldId: string) => void;
  onCopy: (value: string) => void;
  onLocate: (fieldId: string) => void;
  onRegenerateReplace: () => void;
  onFillAllConfirmed: () => void;
}

/** The table's columns, in render order. Keys, so every header is translated. */
const COLUMNS = [
  "colLabel",
  "colState",
  "colSuggested",
  "colSource",
  "colRelevance",
  "colConfidence",
  "colRequired",
  "colMaxLen",
  "colActions",
];

export default function FieldTable({
  response,
  drafts,
  fillResults,
  fillingAll,
  onValueChange,
  onConfirmToggle,
  onFillOne,
  onCopy,
  onLocate,
  onRegenerateReplace,
  onFillAllConfirmed,
}: Props) {
  const { label } = useLabel();

  const resultByField = new Map<string, FillFieldResult>();
  for (const r of fillResults) resultByField.set(r.field_id, r);

  const confirmedCount = response.fields.filter(
    (f) => drafts[f.field_id]?.confirmed && (drafts[f.field_id]?.value ?? "").trim() !== "",
  ).length;

  return (
    <section className="section" aria-label={label("fieldTable")} data-testid="field-table">
      <h2>{label("fieldTable")}</h2>

      <div className="action-row">
        <button
          type="button"
          className="primary small"
          onClick={onFillAllConfirmed}
          disabled={fillingAll || confirmedCount === 0}
        >
          {label("fillAllConfirmed")}
          {confirmedCount > 0 ? ` (${confirmedCount})` : ""}
        </button>
      </div>

      {response.fields.length === 0 ? (
        <p className="note">{label("noFields")}</p>
      ) : (
        // Nine columns will not fit a narrow side panel. The wrapper scrolls,
        // the page does not.
        <div className="field-table-wrap">
          <table className="field-table">
            <thead>
              <tr>
                {COLUMNS.map((column) => (
                  <th key={column}>{label(column)}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {response.fields.map((field) => (
                <FieldRow
                  key={field.field_id}
                  field={field}
                  draft={drafts[field.field_id] as FieldDraft | undefined}
                  fillResult={resultByField.get(field.field_id)}
                  onValueChange={onValueChange}
                  onConfirmToggle={onConfirmToggle}
                  onFillOne={onFillOne}
                  onCopy={onCopy}
                  onLocate={onLocate}
                  onRegenerateReplace={onRegenerateReplace}
                />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
