import { Component, For } from "solid-js";

function humanizeKey(key: string): string {
  const spaced = key
    .replace(/[_-]+/g, " ")
    .replace(/([a-z])([A-Z])/g, "$1 $2")
    .trim();
  if (!spaced) return key;
  return spaced.charAt(0).toUpperCase() + spaced.slice(1).toLowerCase();
}

function formatValue(value: unknown): string {
  if (value === null) return "null";
  if (value === undefined) return "";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (typeof value === "number") {
    if (Number.isInteger(value)) return value.toLocaleString("en-US");
    return value.toLocaleString("en-US", { maximumFractionDigits: 4 });
  }
  return String(value);
}

function isNumericLike(value: unknown): boolean {
  return typeof value === "number";
}

const KeyValueDetails: Component<{ details: Record<string, unknown> }> = (
  props,
) => {
  const entries = () => Object.entries(props.details);

  return (
    <div class="mt-1 border border-theme-border rounded bg-theme-base/40">
      <dl class="divide-y divide-theme-border">
        <For each={entries()}>
          {([key, value]) => (
            <div class="grid grid-cols-[minmax(0,1fr)_minmax(0,1fr)] gap-4 px-3 py-2">
              <dt class="text-xs text-theme-text-secondary">
                {humanizeKey(key)}
              </dt>
              <dd
                class={`text-xs text-theme-text-primary break-words ${
                  isNumericLike(value) ? "tabular-nums text-right" : ""
                }`}
              >
                {formatValue(value)}
              </dd>
            </div>
          )}
        </For>
      </dl>
    </div>
  );
};

export default KeyValueDetails;
