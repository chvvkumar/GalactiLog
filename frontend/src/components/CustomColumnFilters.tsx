import { Component, For, Show, createEffect, createSignal, on, onCleanup } from "solid-js";
import { useDashboardFilters } from "./DashboardFilterProvider";
import { useSettingsContext } from "./SettingsProvider";
import { debounce } from "../utils/debounce";
import type { CustomColumn } from "../types";

const BooleanFilter: Component<{
  column: CustomColumn;
  value: string | undefined;
  onChange: (value: string | null) => void;
}> = (props) => {
  const options = [
    { label: "Any", value: null },
    { label: "Yes", value: "true" },
    { label: "No", value: "false" },
  ] as const;

  return (
    <div class="space-y-1">
      <label class="text-xs text-theme-text-secondary">{props.column.name}</label>
      <div class="flex rounded overflow-hidden border border-theme-border">
        <For each={options}>
          {(opt) => {
            const isActive = () => (props.value ?? null) === opt.value;
            return (
              <button
                onClick={() => props.onChange(opt.value)}
                class="flex-1 px-2 py-1 text-xs transition-colors"
                classList={{
                  "bg-theme-elevated text-theme-text-primary font-medium": isActive(),
                  "bg-theme-input text-theme-text-secondary hover:text-theme-text-primary": !isActive(),
                }}
              >
                {opt.label}
              </button>
            );
          }}
        </For>
      </div>
    </div>
  );
};

const DropdownFilter: Component<{
  column: CustomColumn;
  value: string | undefined;
  onChange: (value: string | null) => void;
}> = (props) => {
  return (
    <div class="space-y-1">
      <label class="text-xs text-theme-text-secondary">{props.column.name}</label>
      <select
        value={props.value ?? ""}
        onChange={(e) => props.onChange(e.currentTarget.value || null)}
        class="w-full px-2 py-1 rounded border border-theme-border bg-theme-input text-theme-text-primary text-sm"
      >
        <option value="">Any</option>
        <For each={props.column.dropdown_options ?? []}>
          {(opt) => <option value={opt}>{opt}</option>}
        </For>
      </select>
    </div>
  );
};

const TextFilter: Component<{
  column: CustomColumn;
  value: string | undefined;
  onChange: (value: string | null) => void;
}> = (props) => {
  const [local, setLocal] = createSignal(props.value ?? "");

  const debouncedUpdate = debounce((value: string) => {
    props.onChange(value || null);
  }, 400);

  // Only sync when external value is cleared (e.g. Reset Filters)
  // Never sync non-empty external values back - input owns its own text
  createEffect(on(() => props.value, (external) => {
    if (external == null || external === "") setLocal("");
  }, { defer: true }));

  const onInput = (value: string) => {
    setLocal(value);
    debouncedUpdate(value);
  };

  return (
    <div class="space-y-1">
      <label class="text-xs text-theme-text-secondary">{props.column.name}</label>
      <input
        type="text"
        value={local()}
        onInput={(e) => onInput(e.currentTarget.value)}
        class="w-full px-2 py-1 rounded border border-theme-border bg-theme-input text-theme-text-primary text-sm"
        placeholder={`Search ${props.column.name}...`}
      />
    </div>
  );
};

type GroupKey = "target" | "session" | "rig";
const GROUP_LABELS: Record<GroupKey, string> = {
  target: "Target",
  session: "Session",
  rig: "Rig",
};
const GROUP_ORDER: GroupKey[] = ["target", "session", "rig"];

const CustomColumnFilters: Component = () => {
  const { customColumnFilters, setCustomColumnFilter } = useDashboardFilters();
  const { customColumns } = useSettingsContext();

  const columns = () => customColumns() ?? [];

  const grouped = () => {
    const groups: Record<GroupKey, CustomColumn[]> = { target: [], session: [], rig: [] };
    for (const col of columns()) {
      groups[col.applies_to as GroupKey]?.push(col);
    }
    for (const key of GROUP_ORDER) {
      groups[key].sort((a, b) => a.display_order - b.display_order);
    }
    return groups;
  };

  const getValue = (slug: string) =>
    customColumnFilters().find((f) => f.slug === slug)?.value;

  return (
    <Show when={columns().length > 0}>
      <div class="space-y-3">
        <For each={GROUP_ORDER}>
          {(groupKey) => (
            <Show when={grouped()[groupKey].length > 0}>
              <div class="space-y-2">
                <span class="text-caption text-theme-text-secondary">{GROUP_LABELS[groupKey]}</span>
                <For each={grouped()[groupKey]}>
                  {(col) => {
                    const value = () => getValue(col.slug);
                    const onChange = (v: string | null) => setCustomColumnFilter(col.slug, v);

                    return (
                      <>
                        {col.column_type === "boolean" && (
                          <BooleanFilter column={col} value={value()} onChange={onChange} />
                        )}
                        {col.column_type === "dropdown" && (
                          <DropdownFilter column={col} value={value()} onChange={onChange} />
                        )}
                        {col.column_type === "text" && (
                          <TextFilter column={col} value={value()} onChange={onChange} />
                        )}
                      </>
                    );
                  }}
                </For>
              </div>
            </Show>
          )}
        </For>
      </div>
    </Show>
  );
};

export default CustomColumnFilters;
