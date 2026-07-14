import { Component, Show, For, createSignal } from "solid-js";
import { DEEP_SKY_TYPES, SOLAR_SYSTEM_TYPES, isSolarSystemType } from "../../constants/objectTypes";
import { showToast } from "../Toast";
import Button from "../ui/Button";

// Coordinates display at most 4 decimals so prefilled FITS/SIMBAD values do not
// surface full float noise (e.g. 83.82208333333334).
const formatCoord = (v: number): string => String(Math.round(v * 10000) / 10000);

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
  const [ra, setRa] = createSignal(initial.ra != null ? formatCoord(initial.ra) : "");
  const [dec, setDec] = createSignal(initial.dec != null ? formatCoord(initial.dec) : "");
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

  // Parse an optional coordinate field. Returns the number, null when blank, or
  // the literal false when the input is invalid (non-numeric or out of range).
  // Number() (unlike parseFloat) rejects trailing garbage like "12abc".
  const parseCoord = (raw: string, min: number, max: number): number | null | false => {
    const trimmed = raw.trim();
    if (!trimmed) return null;
    const n = Number(trimmed);
    if (!Number.isFinite(n) || n < min || n > max) return false;
    return n;
  };

  const handleSubmit = () => {
    const name = primaryName().trim();
    if (!name || props.submitting) return;

    const raValue = parseCoord(ra(), 0, 360);
    if (raValue === false) {
      showToast("RA must be a number between 0 and 360 degrees", "error");
      return;
    }
    const decValue = parseCoord(dec(), -90, 90);
    if (decValue === false) {
      showToast("Dec must be a number between -90 and 90 degrees", "error");
      return;
    }

    const aliases = aliasesText()
      .split(",")
      .map((a) => a.trim())
      .filter((a) => a.length > 0);
    const type = resolvedType();
    props.onSubmit({
      primary_name: name,
      ra: raValue,
      dec: decValue,
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
        <Button
          variant="secondary"
          size="sm"
          onClick={props.onCancel}
        >
          Cancel
        </Button>
        <Button
          variant="primary"
          size="sm"
          onClick={handleSubmit}
          disabled={props.submitting || !primaryName().trim()}
        >
          {props.submitLabel}
        </Button>
      </div>
    </div>
  );
};

export default TargetCreateForm;
