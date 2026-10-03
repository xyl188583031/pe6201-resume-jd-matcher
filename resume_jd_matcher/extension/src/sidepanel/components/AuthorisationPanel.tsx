import type { Authorisation, ModuleName } from "../../types";
import { MODULE_LABELS } from "../../types";
import { useLabel } from "../hooks/useLabel";

interface Props {
  authorisation: Authorisation;
  onToggle: (module: ModuleName) => void;
  onRevokeAll: () => void;
}

export default function AuthorisationPanel({ authorisation, onToggle, onRevokeAll }: Props) {
  const { label } = useLabel();
  const modules = Object.keys(MODULE_LABELS) as ModuleName[];

  return (
    <section className="section" aria-label={label("authorisation")}>
      <h2>{label("authorisation")}</h2>
      <p className="note">{label("authorisationNote")}</p>
      {modules.map((mod) => (
        <div className="checkbox-row" key={mod}>
          <input
            type="checkbox"
            id={`auth-${mod}`}
            checked={authorisation[mod]}
            onChange={() => onToggle(mod)}
          />
          <label htmlFor={`auth-${mod}`}>{label(`module.${mod}`)}</label>
        </div>
      ))}
      <div className="action-row">
        <button type="button" className="small" onClick={onRevokeAll}>
          {label("revokeAll")}
        </button>
      </div>
    </section>
  );
}
