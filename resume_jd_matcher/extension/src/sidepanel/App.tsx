import { useCallback, useEffect, useState } from "react";

import { DEFAULT_STATE, authorisedModules } from "../storage";
import type {
  Authorisation,
  Condition,
  DraftMap,
  ExtensionSettings,
  ExtractResumeResponse,
  FillFieldResult,
  FillFieldsResult,
  GenerateResponse,
  HighlightFieldResult,
  JdFetchResponse,
  ModuleName,
  PanelRequest,
  PanelResponse,
  PersistedState,
  PingResult,
  RawField,
  ScanPageResult,
  UserProfile,
} from "../types";

import StatusBanner from "./components/StatusBanner";
import AuthorisationPanel from "./components/AuthorisationPanel";
import LanguageToggle from "./components/LanguageToggle";
import ProfileForm from "./components/ProfileForm";
import JdPanel from "./components/JdPanel";
import FieldTable from "./components/FieldTable";
import ResumeUpload from "./components/ResumeUpload";
import { useLabel } from "./hooks/useLabel";

/** A repeatable profile module: one whose value is an array of entries. */
type RepeatableModule = "education" | "internship" | "projects";

/**
 * Where the profile in the panel came from.
 *
 * Kept in memory only. Persisting it would mean a schema change to
 * `rjd_state_v1` for a label the user reads once, and a stored "uploaded"
 * that outlived the user editing every field by hand afterwards would be a
 * lie rather than a memory. Session-scoped, it can only describe what just
 * happened.
 */
type ProfileSource = "manual" | "uploaded";

/**
 * The flow the panel is designed around, in order.
 *
 * It is *derived* from the state rather than stored: every step is a question
 * about what the user has done, so there is no second source of truth to keep in
 * step. The strip below the title shows where the user is; the sections
 * themselves stay mounted, because hiding a section the user has already filled
 * in would throw their work off the screen the moment they ticked a box.
 */
const FLOW_STEPS = [
  "authorise",
  "profile",
  "scan",
  "jd",
  "generate",
  "review",
  "fill",
] as const;

type FlowStep = (typeof FLOW_STEPS)[number];

const STEP_LABELS: Record<FlowStep, string> = {
  authorise: "stepAuthorise",
  profile: "stepProfile",
  scan: "stepScan",
  jd: "stepJd",
  generate: "stepGenerate",
  review: "stepReview",
  fill: "stepFill",
};

export default function App() {
  const { label } = useLabel();

  // ---- persisted state (mirrors PersistedState) ----
  const [settings, setSettings] = useState<ExtensionSettings>(DEFAULT_STATE.settings);
  const [profile, setProfile] = useState<UserProfile>(DEFAULT_STATE.profile);
  const [authorisation, setAuthorisation] = useState<Authorisation>(DEFAULT_STATE.authorisation);
  const [jdText, setJdText] = useState<string>(DEFAULT_STATE.jdText);
  const [jdUrl, setJdUrl] = useState<string>(DEFAULT_STATE.jdUrl);
  const [drafts, setDrafts] = useState<DraftMap>(DEFAULT_STATE.drafts);

  // ---- runtime state (not persisted) ----
  /** Where the profile came from *this session*; see `ProfileSource`. */
  const [profileSource, setProfileSource] = useState<ProfileSource>("manual");
  const [ping, setPing] = useState<PingResult | null>(null);
  const [scanResult, setScanResult] = useState<ScanPageResult | null>(null);
  const [generateResponse, setGenerateResponse] = useState<GenerateResponse | null>(null);
  const [jdFetched, setJdFetched] = useState<JdFetchResponse | null>(null);
  const [jdFetchError, setJdFetchError] = useState<string | null>(null);
  const [fillResults, setFillResults] = useState<FillFieldResult[]>([]);

  const [error, setError] = useState<string | null>(null);
  const [pinging, setPinging] = useState(false);
  const [scanning, setScanning] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [fetching, setFetching] = useState(false);
  const [fillingAll, setFillingAll] = useState(false);

  /* ----------------------------------------------------------- messaging */

  /**
   * The only channel to the backend. Wraps `chrome.runtime.sendMessage` so a
   * missing background worker, `lastError`, or an `undefined` response become a
   * tidy `{ ok: false }` instead of an unhandled promise rejection.
   */
  const talk = useCallback(<T,>(request: PanelRequest): Promise<PanelResponse<T>> => {
    return new Promise((resolve) => {
      try {
        chrome.runtime.sendMessage(request, (response: PanelResponse<T> | undefined) => {
          const lastErr = chrome.runtime.lastError;
          if (lastErr) {
            resolve({ ok: false, error: lastErr.message });
            return;
          }
          if (response === undefined) {
            resolve({ ok: false, error: label("bgNoResponse") });
            return;
          }
          resolve(response);
        });
      } catch (e) {
        resolve({
          ok: false,
          error: e instanceof Error ? e.message : String(e),
        });
      }
    });
  }, [label]);

  /** Send a request and surface failures as the panel's error string. */
  const request = useCallback(
    async <T,>(request: PanelRequest): Promise<T | null> => {
      const response = await talk<T>(request);
      if (!response.ok) {
        setError(response.error ?? label("error"));
        return null;
      }
      return response.data ?? null;
    },
    [talk, label],
  );

  /** Persist a partial state patch to the background worker's storage. */
  const save = useCallback(
    (patch: Partial<PersistedState>) => {
      void request<PersistedState>({ type: "RJD_SAVE_STATE", patch });
    },
    [request],
  );

  /* -------------------------------------------------------------- lifecycle */

  // On mount: load persisted state, then probe the backend once.
  useEffect(() => {
    void loadStateAndPing();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function loadStateAndPing() {
    const state = await request<PersistedState>({ type: "RJD_GET_STATE" });
    if (state) {
      setSettings(state.settings);
      setProfile(state.profile);
      setAuthorisation(state.authorisation);
      setJdText(state.jdText);
      setJdUrl(state.jdUrl);
      setDrafts(state.drafts);
    }
    await doPing();
  }

  const doPing = useCallback(async () => {
    setError(null);
    setPinging(true);
    const result = await request<PingResult>({ type: "RJD_PING" });
    setPinging(false);
    if (result) setPing(result);
  }, [request]);

  /* --------------------------------------------------------------- settings */

  function updateSetting<K extends keyof ExtensionSettings>(
    key: K,
    value: ExtensionSettings[K],
  ) {
    const next = { ...settings, [key]: value };
    setSettings(next);
    save({ settings: next });
  }

  /* ----------------------------------------------------------- authorisation */

  function toggleAuth(mod: ModuleName) {
    const next = { ...authorisation, [mod]: !authorisation[mod] };
    setAuthorisation(next);
    save({ authorisation: next });
  }

  function revokeAll() {
    const next: Authorisation = {
      personal_info: false,
      internship: false,
      projects: false,
      education: false,
    };
    setAuthorisation(next);
    save({ authorisation: next });
  }

  /* ----------------------------------------------------------------- profile */

  function updatePersonal(key: string, value: string) {
    setProfile((p) => ({ ...p, personal_info: { ...p.personal_info, [key]: value } }));
  }

  function updateEntry(module: RepeatableModule, index: number, key: string, value: string) {
    const list = profile[module] as Array<Record<string, string | undefined>>;
    const copy = list.map((entry, i) => (i === index ? { ...entry, [key]: value } : entry));
    setProfile((p) => ({ ...p, [module]: copy }));
  }

  function addEntry(module: RepeatableModule) {
    const list = profile[module] as Array<Record<string, string | undefined>>;
    const next = { ...profile, [module]: [...list, {}] } as unknown as UserProfile;
    setProfile(next);
    persistProfile(next);
  }

  function removeEntry(module: RepeatableModule, index: number) {
    const list = profile[module] as Array<Record<string, string | undefined>>;
    const next = {
      ...profile,
      [module]: list.filter((_, i) => i !== index),
    } as unknown as UserProfile;
    setProfile(next);
    persistProfile(next);
  }

  function persistProfile(next: UserProfile = profile) {
    save({ profile: next });
  }

  /* --------------------------------------------------------- resume upload */

  /**
   * Resume text -> a profile, through the background worker.
   *
   * The panel has already read the PDF (see `pdf.ts`); this is the only place
   * that text goes anywhere. `request` puts a failure on the panel's error
   * banner and resolves `null`, which is what tells the upload component to stop
   * waiting instead of sitting on "extracting" for ever.
   */
  const doExtractResume = useCallback(
    (text: string): Promise<ExtractResumeResponse | null> =>
      request<ExtractResumeResponse>({ type: "RJD_EXTRACT_RESUME", text }),
    [request],
  );

  /**
   * Write an extracted profile into the one profile slot the panel has.
   *
   * Deliberately the same slot the manual form writes to. A second, parallel
   * "uploaded profile" would be a second source of truth, and the two would
   * disagree the moment the user corrected one of them.
   */
  function applyExtractedProfile(response: ExtractResumeResponse) {
    const next = response.profile;
    setProfile(next);
    setProfileSource("uploaded");
    persistProfile(next);
  }

  /* --------------------------------------------------------------------- jd */

  function onJdText(value: string) {
    setJdText(value);
  }
  function onJdUrl(value: string) {
    setJdUrl(value);
  }
  function persistJd() {
    save({ jdText, jdUrl });
  }

  async function doJdFetch() {
    setError(null);
    setFetching(true);
    setJdFetchError(null);
    const response = await talk<JdFetchResponse>({ type: "RJD_JD_FETCH", url: jdUrl });
    setFetching(false);
    if (response.ok && response.data) {
      setJdFetched(response.data);
      // The fetched text becomes the JD text the user can edit and send.
      setJdText(response.data.text);
      save({ jdText: response.data!.text });
    } else {
      // Show the server's `message` verbatim; never silently fall back to paste.
      setJdFetchError(response.error ?? response.data?.message ?? label("error"));
    }
  }

  /* ------------------------------------------------------------------- scan */

  async function doScan() {
    setError(null);
    setScanning(true);
    const result = await request<ScanPageResult>({ type: "RJD_SCAN" });
    setScanning(false);
    if (result) setScanResult(result);
  }

  /* --------------------------------------------------------------- generate */

  async function doGenerate(overwriteFilled = false) {
    setError(null);
    setGenerating(true);
    const result = await request<GenerateResponse>({
      type: "RJD_GENERATE",
      overwriteFilled,
    });
    setGenerating(false);
    if (result) {
      setGenerateResponse(result);
      // Build drafts, preserving any row the user already edited: the client
      // half of "the user's edit wins". An edited row is never overwritten by a
      // re-generation, even though the server also refuses to overwrite it.
      setDrafts((prev) => buildDrafts(prev, result));
    }
  }

  function buildDrafts(prev: DraftMap, response: GenerateResponse): DraftMap {
    const next: DraftMap = {};
    for (const field of response.fields) {
      const existing = prev[field.field_id];
      if (existing && existing.edited) {
        next[field.field_id] = existing;
      } else {
        next[field.field_id] = {
          field_id: field.field_id,
          value: field.suggested_value ?? field.current_value ?? "",
          edited: false,
          // Keep confirmation across re-generation for rows the user has not edited.
          confirmed: existing?.confirmed ?? false,
        };
      }
    }
    return next;
  }

  /* -------------------------------------------------------------- fill flow */

  async function doFillOne(fieldId: string) {
    setError(null);
    const draft = drafts[fieldId];
    if (!draft || draft.value.trim() === "") return;
    const result = await request<FillFieldsResult>({
      type: "RJD_FILL",
      values: { [fieldId]: draft.value },
    });
    if (result) setFillResults(result.results);
  }

  async function doFillAllConfirmed() {
    setError(null);
    if (!generateResponse) return;
    const values: Record<string, string> = {};
    for (const field of generateResponse.fields) {
      const draft = drafts[field.field_id];
      if (draft && draft.confirmed && draft.value.trim() !== "") {
        values[field.field_id] = draft.value;
      }
    }
    setFillingAll(true);
    const result = await request<FillFieldsResult>({ type: "RJD_FILL", values });
    setFillingAll(false);
    if (result) setFillResults(result.results);
  }

  async function doCopy(value: string) {
    try {
      await navigator.clipboard.writeText(value);
    } catch {
      setError(label("copyFailed"));
    }
  }

  async function doLocate(fieldId: string) {
    setError(null);
    await request<HighlightFieldResult>({ type: "RJD_HIGHLIGHT", fieldId });
  }

  /* ----------------------------------------------------------- draft edits */

  function onValueChange(fieldId: string, value: string) {
    const current = drafts[fieldId];
    const next: DraftMap = {
      ...drafts,
      [fieldId]: {
        field_id: fieldId,
        value,
        edited: true,
        confirmed: current?.confirmed ?? false,
      },
    };
    setDrafts(next);
    save({ drafts: next });
  }

  function onConfirmToggle(fieldId: string) {
    const current = drafts[fieldId];
    const next: DraftMap = {
      ...drafts,
      [fieldId]: {
        field_id: fieldId,
        value: current?.value ?? "",
        edited: current?.edited ?? false,
        confirmed: !(current?.confirmed ?? false),
      },
    };
    setDrafts(next);
    save({ drafts: next });
  }

  /* ---------------------------------------------------------------- render */

  const scan = scanResult ? deriveScanCounts(scanResult.fields) : null;
  const currentStep = deriveStep({
    authorised: authorisedModules(authorisation).length > 0,
    profileFilled: profileHasContent(profile),
    scanned: scanResult !== null,
    jdPresent: jdText.trim() !== "",
    generated: generateResponse !== null,
    filled: fillResults.some((r) => r.ok),
  });

  return (
    <div className="app" data-testid="panel-root">
      {/* Mounted first, outside the flow: switching language is a reading
          decision, not a step in the form-filling workflow. */}
      <LanguageToggle />

      <header className="sticky-header">
        {/* The title block reserves the top-right corner for the fixed language
            toggle; see `--toggle-rail` in styles.css. */}
        <div className="title-row">
          <div className="title">{label("appTitle")}</div>
          <div className="subtitle">{label("appSubtitle")}</div>
        </div>

        <ol className="flow-strip" aria-label={label("flowTitle")} data-testid="flow-strip">
          {FLOW_STEPS.map((step) => (
            <li
              key={step}
              className={step === currentStep ? "active" : ""}
              data-step={step}
              data-active={step === currentStep ? "true" : "false"}
            >
              {label(STEP_LABELS[step])}
            </li>
          ))}
        </ol>

        <StatusBanner ping={ping} loading={pinging} onRecheck={() => void doPing()} />

        <div className="action-row">
          <button
            type="button"
            className="primary"
            onClick={() => void doScan()}
            disabled={scanning}
            data-testid="scan-button"
          >
            {scanning ? label("scanning") : label("scan")}
          </button>
          <button
            type="button"
            className="primary"
            onClick={() => void doGenerate(false)}
            disabled={generating}
            data-testid="generate-button"
          >
            {generating ? label("generating") : label("generate")}
          </button>
        </div>
      </header>

      <main className="content">
        {error && (
          <div className="offline-warn" role="alert">
            {label("error")}: {error}
          </div>
        )}

        {/* Settings */}
        <section className="section" aria-label={label("settings")}>
          <h2>{label("settings")}</h2>

          <label htmlFor="set-base">{label("baseUrl")}</label>
          <input
            id="set-base"
            type="text"
            value={settings.baseUrl}
            onChange={(e) => updateSetting("baseUrl", e.target.value)}
          />
          <p className="note">{label("baseUrlHint")}</p>

          <label htmlFor="set-token">{label("token")}</label>
          <input
            id="set-token"
            type="password"
            value={settings.token}
            onChange={(e) => updateSetting("token", e.target.value)}
          />
          <p className="note">{label("tokenHint")}</p>

          <label htmlFor="set-apikey">{label("apiKey")}</label>
          <input
            id="set-apikey"
            type="password"
            value={settings.apiKey}
            onChange={(e) => updateSetting("apiKey", e.target.value)}
          />
          <p className="note">{label("apiKeyHint")}</p>

          <label htmlFor="set-condition">{label("condition")}</label>
          <select
            id="set-condition"
            value={settings.condition}
            onChange={(e) => updateSetting("condition", e.target.value as Condition)}
          >
            <option value="A">{label("conditionA")}</option>
            <option value="B">{label("conditionB")}</option>
            <option value="C">{label("conditionC")}</option>
          </select>
        </section>

        <AuthorisationPanel
          authorisation={authorisation}
          onToggle={toggleAuth}
          onRevokeAll={revokeAll}
        />

        <ResumeUpload
          onExtract={doExtractResume}
          onApply={applyExtractedProfile}
          applied={profileSource === "uploaded"}
        />

        {profileSource === "uploaded" && (
          <p className="note" data-testid="profile-source">
            {label("sourceUploaded")}
          </p>
        )}

        <ProfileForm
          profile={profile}
          authorisation={authorisation}
          onPersonalChange={updatePersonal}
          onEntryChange={updateEntry}
          onAddEntry={addEntry}
          onRemoveEntry={removeEntry}
          onPersist={() => persistProfile()}
        />

        <JdPanel
          jdText={jdText}
          jdUrl={jdUrl}
          onTextChange={onJdText}
          onUrlChange={onJdUrl}
          onPersist={persistJd}
          onFetch={() => void doJdFetch()}
          fetching={fetching}
          fetched={jdFetched}
          fetchError={jdFetchError}
        />

        {scanResult && scan && (
          <section className="section" aria-label={label("scanSummary")}>
            <h2>{label("scanSummary")}</h2>
            <div className="counts-line">
              <span>
                {label("scanSummary")} · {label("colLabel")}: <b>{scan.total}</b>
              </span>
              <span>
                {label("colRequired")}: <b>{scan.required}</b>
              </span>
              <span>
                {label("chipAlreadyFilled")}: <b>{scan.alreadyFilled}</b>
              </span>
              <span>
                {label("chipOffered")}: <b>{scan.fillable}</b>
              </span>
              <span>
                {label("chipSensitive")}: <b>—</b>
              </span>
              <span>
                {label("chipNotFillable")}: <b>—</b>
              </span>
            </div>
            <p className="note">
              {scanResult.url} · {scanResult.pageTitle}
            </p>
          </section>
        )}

        {generateResponse && (
          <>
            <FieldTable
              response={generateResponse}
              drafts={drafts}
              fillResults={fillResults}
              fillingAll={fillingAll}
              onValueChange={onValueChange}
              onConfirmToggle={onConfirmToggle}
              onFillOne={(id) => void doFillOne(id)}
              onCopy={(v) => void doCopy(v)}
              onLocate={(id) => void doLocate(id)}
              onRegenerateReplace={() => void doGenerate(true)}
              onFillAllConfirmed={() => void doFillAllConfirmed()}
            />

            <ServerNotes response={generateResponse} />
          </>
        )}
      </main>
    </div>
  );
}

/* ----------------------------------------------------- pure render helpers */

function deriveStep(state: {
  authorised: boolean;
  profileFilled: boolean;
  scanned: boolean;
  jdPresent: boolean;
  generated: boolean;
  filled: boolean;
}): FlowStep {
  if (!state.authorised) return "authorise";
  if (!state.profileFilled) return "profile";
  if (!state.scanned) return "scan";
  if (!state.jdPresent) return "jd";
  if (!state.generated) return "generate";
  if (!state.filled) return "review";
  return "fill";
}

/** Does the profile hold anything the assistant could draft from? */
function profileHasContent(profile: UserProfile): boolean {
  const personal = Object.values(profile.personal_info ?? {}).some(
    (v) => typeof v === "string" && v.trim() !== "",
  );
  return (
    personal ||
    profile.education.length > 0 ||
    profile.internship.length > 0 ||
    profile.projects.length > 0
  );
}

function deriveScanCounts(fields: RawField[]) {
  const total = fields.length;
  const required = fields.filter((f) => f.required).length;
  const alreadyFilled = fields.filter((f) => (f.current_value ?? "").trim() !== "").length;
  const fillable = total - alreadyFilled;
  return { total, required, alreadyFilled, fillable };
}

function ServerNotes({ response }: { response: GenerateResponse }) {
  const { label } = useLabel();
  const { privacy, jd_analysis: jd, counts } = response;
  const dropped = privacy.dropped_modules ?? [];

  return (
    <section className="section" aria-label={label("warnings")}>
      <details className="collapsible">
        <summary>{label("warnings")}</summary>

        {response.risk_flags.length > 0 && (
          <>
            <strong>{label("riskFlags")}</strong>
            <ul className="warn-list">
              {response.risk_flags.map((r, i) => (
                <li key={i}>{r}</li>
              ))}
            </ul>
          </>
        )}

        {response.overall_suggestions.length > 0 && (
          <>
            <strong>{label("overallSuggestions")}</strong>
            <ul className="warn-list">
              {response.overall_suggestions.map((s, i) => (
                <li key={i}>{s}</li>
              ))}
            </ul>
          </>
        )}

        {response.notes.length > 0 && (
          <>
            <strong>{label("notes")}</strong>
            <ul className="warn-list">
              {response.notes.map((n, i) => (
                <li key={i}>{n}</li>
              ))}
            </ul>
          </>
        )}

        <strong>{label("privacy")}</strong>
        <ul className="warn-list">
          <li>
            {label("authorisedModules")}: {privacy.authorised_modules.join(", ") || label("none")}
          </li>
          <li>
            {label("usedModules")}: {privacy.used_modules.join(", ") || label("none")}
          </li>
          <li>
            {label("droppedModules")}: {dropped.join(", ") || label("none")}
          </li>
        </ul>
        {dropped.length > 0 && (
          <div className="fallback-reason" role="alert">
            {label("droppedWarning")}
          </div>
        )}

        <strong>{label("jdAnalysis")}</strong>
        <dl className="jd-analysis">
          <dt>{label("jobTitle")}</dt>
          <dd>{jd.job_title || label("none")}</dd>
          <dt>{label("company")}</dt>
          <dd>{jd.company || label("none")}</dd>
          <dt>{label("location")}</dt>
          <dd>{jd.location || label("none")}</dd>

          {jd.requirements.length > 0 && (
            <>
              <dt>{label("requirements")}</dt>
              <dd>
                <ul className="warn-list">
                  {jd.requirements.map((r, i) => (
                    <li key={i}>{r}</li>
                  ))}
                </ul>
              </dd>
            </>
          )}

          {jd.keywords.length > 0 && (
            <>
              <dt>{label("keywords")}</dt>
              <dd>{jd.keywords.join(", ")}</dd>
            </>
          )}

          {jd.bonus_points.length > 0 && (
            <>
              <dt>{label("bonusPoints")}</dt>
              <dd>{jd.bonus_points.join(", ")}</dd>
            </>
          )}

          {jd.missing_from_user_profile.length > 0 && (
            <>
              <dt>{label("missingFromProfile")}</dt>
              <dd>
                <ul className="warn-list">
                  {jd.missing_from_user_profile.map((r, i) => (
                    <li key={i}>{r}</li>
                  ))}
                </ul>
              </dd>
            </>
          )}
        </dl>

        <p className="note">
          {label("notes")} · {label("chipOffered")}: {counts.suggestion_offered} ·{" "}
          {label("chipSensitive")}: {counts.sensitive_skipped} · {label("chipMissing")}:{" "}
          {counts.missing} · {label("chipDeclined")}: {counts.withheld_low_confidence} ·{" "}
          {label("chipAlreadyFilled")}: {counts.already_filled}
        </p>
      </details>
    </section>
  );
}
