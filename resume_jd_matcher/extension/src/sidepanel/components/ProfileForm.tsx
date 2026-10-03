import type {
  Authorisation,
  EducationEntry,
  ExperienceEntry,
  ModuleName,
  ProjectEntry,
  UserProfile,
} from "../../types";
import { MODULE_LABELS } from "../../types";
import { useLabel } from "../hooks/useLabel";
import { profileFieldOrder } from "../labels";

type RepeatableModule = "education" | "internship" | "projects";

interface Props {
  profile: UserProfile;
  authorisation: Authorisation;
  /** Update one key of personal_info. */
  onPersonalChange: (key: string, value: string) => void;
  /** Update one key of a repeatable module entry. */
  onEntryChange: (module: RepeatableModule, index: number, key: string, value: string) => void;
  /** Add / remove a repeatable entry. */
  onAddEntry: (module: RepeatableModule) => void;
  onRemoveEntry: (module: RepeatableModule, index: number) => void;
  /** Persist the profile to storage (called on blur). */
  onPersist: () => void;
}

const PERSONAL_KEYS = ["full_name", "email", "phone", "location", "linkedin", "github", "portfolio"];

export default function ProfileForm({
  profile,
  authorisation,
  onPersonalChange,
  onEntryChange,
  onAddEntry,
  onRemoveEntry,
  onPersist,
}: Props) {
  const { label } = useLabel();

  // Only render the modules the user has authorised. A module that is not
  // authorised must not even show its inputs (task section 4).
  const visibleModules = (Object.keys(MODULE_LABELS) as ModuleName[]).filter(
    (m) => authorisation[m],
  );

  return (
    <section className="section" aria-label={label("profile")} data-testid="profile-form">
      <h2>{label("profile")}</h2>
      <p className="note">{label("profileNote")}</p>

      {visibleModules.map((mod) => {
        if (mod === "personal_info") {
          return (
            <fieldset key={mod} style={{ border: "none", padding: 0, margin: 0 }}>
              <legend style={{ fontWeight: 700 }}>{label(`module.${mod}`)}</legend>
              {PERSONAL_KEYS.map((key) => (
                <label key={key} htmlFor={`pi-${key}`}>
                  {label(`field.${key}`)}
                  <input
                    id={`pi-${key}`}
                    type="text"
                    value={profile.personal_info[key] ?? ""}
                    onChange={(e) => onPersonalChange(key, e.target.value)}
                    onBlur={onPersist}
                  />
                </label>
              ))}
            </fieldset>
          );
        }

        const list = listFor(profile, mod);
        return (
          <fieldset key={mod} style={{ border: "none", padding: 0, margin: "8px 0 0" }}>
            <legend style={{ fontWeight: 700 }}>{label(`module.${mod}`)}</legend>
            {list.map((entry, index) => (
              <div
                key={index}
                style={{
                  border: "1px solid var(--border)",
                  borderRadius: 6,
                  padding: 6,
                  marginBottom: 6,
                }}
              >
                {profileFieldOrder[mod].map((key) => (
                  <label key={key} htmlFor={`${mod}-${index}-${key}`}>
                    {label(`field.${key}`)}
                    <input
                      id={`${mod}-${index}-${key}`}
                      type="text"
                      value={String(entry[key] ?? "")}
                      onChange={(e) => onEntryChange(mod, index, key, e.target.value)}
                      onBlur={onPersist}
                    />
                  </label>
                ))}
                <button type="button" className="small" onClick={() => onRemoveEntry(mod, index)}>
                  {label("remove")}
                </button>
              </div>
            ))}
            <button type="button" className="small" onClick={() => onAddEntry(mod)}>
              {`${label("add")} ${label(`module.${mod}`)}`}
            </button>
          </fieldset>
        );
      })}
    </section>
  );
}

function listFor(
  profile: UserProfile,
  mod: RepeatableModule,
): Array<EducationEntry | ExperienceEntry | ProjectEntry> {
  if (mod === "education") return profile.education;
  if (mod === "internship") return profile.internship;
  return profile.projects;
}
