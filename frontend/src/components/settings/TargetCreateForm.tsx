import { Component, Show, For, createSignal } from "solid-js";
import { DEEP_SKY_TYPES, SOLAR_SYSTEM_TYPES, isSolarSystemType } from "../../constants/objectTypes";

export interface TargetFormValues {
  primary_name: string;
  ra: number | null;
  dec: number | null;
  object_type: string | null;
  catalog_id: string | null;
  aliases: string[];
  user_defined: boolean;
}

interface Props {
  initial?: Partial<TargetFormValues>;
  submitLabel: string;
  submitting: boolean;
  onSubmit: (values: TargetFormValues) => void;
  onCancel: () => void;
}

const inputClass = "w-full px-2 py-1.5 text-sm bg-theme-base border border-theme-border rounded-[var(--radius-sm)] text-theme-text-primary focus:border-theme-accent focus:outline-none";
const labelClass = "block text-xs text-theme-text-secondary mb-1";

// All recognized categories; anything else is edited through the "Other..." escape hatch.
const KNOWN_TYPES: readonly string[] = [...DEEP_SKY_TYPES, ...SOLAR_SYSTEM_TYPES];

const TargetCreateForm: Component<Props> = (props) => {
  const initial = props.initial ?? {};
  const initialType = initial.object_type ?? "";
  // A non-empty type that is not a known category is edited as free text via "Other".
  const startsOther = initialType !== "" && !KNOWN_TYPES.includes(initialType);

  const [primaryName, setPrimaryName] = createSignal(initial.primary_name ?? "");
  const [ra, setRa] = createSignal(initial.ra != null ? String(initial.ra) : "");
  const [dec, setDec] = createSignal(initial.dec != null ? String(initial.dec) : "");
  const [typeChoice, setTypeChoice] = createSignal(startsOther ? "__other__" : initialType);
  const [otherType, setOtherType] = createSignal(startsOther ? initialType : "");
  const [catalogId, setCatalogId] = createSignal(initial.catalog_id ?? "");
  const [aliasesText, setAliasesText] = createSignal((initial.aliases ?? []).join(", "));
  const [userDefined, setUserDefined] = createSignal(initial.user_defined ?? false);

  const resolvedType = (): string => {
    const choice = typeChoice();
    if (choice === "__other__") return otherType().trim();
    return choice;
  };

  const handleTypeChange = (value: string) => {
    setTypeChoice(value);
    // Selecting a solar-system type implies a moving object: clear coordinates
    // (a fixed FITS position is meaningless) and flag it as custom.
    if (value !== "__other__" && isSolarSystemType(value)) {
      setRa("");
      setDec("");
      setUserDefined(true);
    }
  };

  const handleSubmit = () => {
    const name = primaryName().trim();
    if (!name || props.submitting) return;
    const aliases = aliasesText()
      .split(",")
      .map((a) => a.trim())
      .filter((a) => a.length > 0);
    const type = resolvedType();
    props.onSubmit({
      primary_name: name,
      ra: ra().trim() ? parseFloat(ra()) : null,
      dec: dec().trim() ? parseFloat(dec()) : null,
      object_type: type || null,
      catalog_id: catalogId().trim() || null,
      aliases,
      user_defined: userDefined(),
    });
  };

  return (
    <div class="space-y-3">
      <div>
        <label class={labelClass}>Primary Name</label>
        <input type="text" class={inputClass} value={primaryName()} onInput={(e) => setPrimaryName(e.currentTarget.value)} />
      </div>

      <div>
        <label class={labelClass}>Object Type</label>
        <select class={inputClass} value={typeChoice()} onChange={(e) => handleTypeChange(e.currentTarget.value)}>
          <option value="">Unspecified</option>
          <optgroup label="Deep Sky">
            <For each={DEEP_SKY_TYPES}>{(t) => <option value={t}>{t}</option>}</For>
          </optgroup>
          <optgroup label="Solar System">
            <For each={SOLAR_SYSTEM_TYPES}>{(t) => <option value={t}>{t}</option>}</For>
          </optgroup>
          <option value="__other__">Other...</option>
        </select>
        <Show when={typeChoice() === "__other__"}>
          <input
            type="text"
            class={`${inputClass} mt-2`}
            value={otherType()}
            onInput={(e) => setOtherType(e.currentTarget.value)}
            placeholder="Custom object type"
          />
        </Show>
      </div>

      <div class="grid grid-cols-2 gap-3">
        <div>
          <label class={labelClass}>RA (degrees)</label>
          <input type="text" class={inputClass} value={ra()} onInput={(e) => setRa(e.currentTarget.value)} placeholder="Optional" />
        </div>
        <div>
          <label class={labelClass}>Dec (degrees)</label>
          <input type="text" class={inputClass} value={dec()} onInput={(e) => setDec(e.currentTarget.value)} placeholder="Optional" />
        </div>
      </div>

      <div>
        <label class={labelClass}>Catalog ID</label>
        <input type="text" class={inputClass} value={catalogId()} onInput={(e) => setCatalogId(e.currentTarget.value)} placeholder="e.g. NGC 1234, IC 456" />
      </div>

      <div>
        <label class={labelClass}>Aliases</label>
        <input type="text" class={inputClass} value={aliasesText()} onInput={(e) => setAliasesText(e.currentTarget.value)} placeholder="Comma-separated alternate names" />
      </div>

      <label class="flex items-center gap-2 text-sm text-theme-text-primary cursor-pointer">
        <input type="checkbox" checked={userDefined()} onChange={(e) => setUserDefined(e.currentTarget.checked)} />
        Custom target (skip catalog lookups)
      </label>

      <div class="flex justify-end gap-2 pt-2">
        <button
          onClick={props.onCancel}
          class="px-3 py-1.5 text-sm border border-theme-border text-theme-text-secondary rounded-[var(--radius-sm)] hover:text-theme-text-primary transition-colors"
        >
          Cancel
        </button>
        <button
          onClick={handleSubmit}
          disabled={props.submitting || !primaryName().trim()}
          class="px-3 py-1.5 text-sm bg-theme-accent/15 text-theme-accent border border-theme-accent/30 rounded-[var(--radius-sm)] hover:bg-theme-accent/25 transition-colors disabled:opacity-50"
        >
          {props.submitLabel}
        </button>
      </div>
    </div>
  );
};

export default TargetCreateForm;
