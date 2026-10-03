import type { PingResult } from "../../types";
import { useLabel } from "../hooks/useLabel";

interface Props {
  ping: PingResult | null;
  loading: boolean;
  onRecheck: () => void;
}

export default function StatusBanner({ ping, loading, onRecheck }: Props) {
  const { label } = useLabel();
  const up = ping?.backendUp ?? false;
  const mode = ping?.health?.mode ?? "";
  const offline = mode === "offline_stub";
  const prototype = ping?.health?.prototype_banner ?? "";

  return (
    <section className="status-banner" aria-label={label("connection")}>
      <div className="status-line">
        <span className={`dot ${up ? "up" : "down"}`} aria-hidden="true" />
        <strong>{up ? label("backendUp") : label("backendDown")}</strong>
        {/* The mode string comes from the server (`live_api` / `offline_stub`)
            and is an identifier, not prose, so it is shown as it arrives. */}
        <span className="en">{up && mode ? `(${mode})` : ""}</span>
      </div>

      {offline && (
        <div className="offline-warn" role="alert">
          {label("offlineWarning")}
        </div>
      )}

      <div className="status-line">
        <span>{label("model")}:</span>
        <span>{ping?.health?.model ?? label("unknown")}</span>
      </div>

      <div className="status-line">
        <span>{label("authRequired")}:</span>
        <span>{ping?.health?.auth_required ? label("authRequired") : label("noAuth")}</span>
      </div>

      <div className="status-line">
        <span>{label("tabUsable")}:</span>
        <span>{ping?.tabUsable ? label("tabUsable") : label("tabNotUsable")}</span>
      </div>

      <div className="status-line">
        <span>{label("scannedFields")}:</span>
        <span>{ping?.scannedFields ?? 0}</span>
      </div>

      {prototype && <div className="prototype-banner">{prototype}</div>}

      <div className="action-row">
        <button
          type="button"
          className="small"
          onClick={onRecheck}
          disabled={loading}
          data-testid="recheck-button"
        >
          {loading ? label("scanning") : label("recheck")}
        </button>
      </div>
    </section>
  );
}
