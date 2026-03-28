import { Component, For, Show, createResource } from "solid-js";
import { useCatalog } from "../store/catalog";
import { api } from "../api/client";

const ObjectTypeToggles: Component = () => {
  const { filters, toggleObjectType } = useCatalog();
  const [objectTypes] = createResource(() => api.getObjectTypes());

  const isActive = (t: string) => filters().objectTypes.includes(t);

  return (
    <div class="space-y-2">
      <label class="text-[11px] font-medium uppercase tracking-wider text-theme-text-tertiary">Object Type</label>
      <Show when={objectTypes() && objectTypes()!.length > 0}>
        <div class="flex gap-1.5 flex-wrap">
          <For each={objectTypes()}>
            {(item) => (
              <button
                onClick={() => toggleObjectType(item.object_type)}
                class={`px-1.5 h-6 rounded text-[10px] font-bold flex items-center justify-center transition-all ${
                  isActive(item.object_type)
                    ? "ring-1 ring-theme-accent bg-theme-elevated text-theme-accent brightness-110"
                    : "ring-1 ring-transparent bg-theme-elevated text-theme-text-secondary hover:brightness-110"
                }`}
                title={`${item.object_type} (${item.count})`}
              >
                {item.object_type}
                <span class="ml-1 opacity-60">{item.count}</span>
              </button>
            )}
          </For>
        </div>
      </Show>
    </div>
  );
};

export default ObjectTypeToggles;
