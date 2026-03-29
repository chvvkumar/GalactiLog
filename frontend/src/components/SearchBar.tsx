import { Component, createSignal, For, Show } from "solid-js";
import { api } from "../api/client";
import { useCatalog } from "../store/catalog";
import type { TargetSearchResultFuzzy } from "../types";

const SearchBar: Component = () => {
  const { updateFilter } = useCatalog();
  const [query, setQuery] = createSignal("");
  const [suggestions, setSuggestions] = createSignal<TargetSearchResultFuzzy[]>([]);
  const [showSuggestions, setShowSuggestions] = createSignal(false);

  let debounceTimer: ReturnType<typeof setTimeout>;

  const onInput = (value: string) => {
    setQuery(value);
    clearTimeout(debounceTimer);
    if (value.length < 2) {
      setSuggestions([]);
      setShowSuggestions(false);
      updateFilter("searchQuery", value);
      return;
    }
    debounceTimer = setTimeout(async () => {
      try {
        const results = await api.searchTargets(value);
        setSuggestions(results);
        setShowSuggestions(results.length > 0);
      } catch {
        setSuggestions([]);
      }
      updateFilter("searchQuery", value);
    }, 300);
  };

  const selectTarget = (target: TargetSearchResultFuzzy) => {
    setQuery(target.primary_name);
    setShowSuggestions(false);
    updateFilter("searchQuery", target.primary_name);
  };

  return (
    <div class="relative">
      <label class="text-label font-medium uppercase tracking-wider text-theme-text-tertiary mb-1 block">Search Targets</label>
      <input
        type="text"
        value={query()}
        onInput={(e) => onInput(e.currentTarget.value)}
        onFocus={() => suggestions().length > 0 && setShowSuggestions(true)}
        onBlur={() => setTimeout(() => setShowSuggestions(false), 200)}
        placeholder="M31, NGC 7000..."
        class="w-full px-3 py-2 bg-theme-input border border-theme-border rounded-[var(--radius-sm)] text-sm text-theme-text-primary placeholder:text-theme-text-tertiary focus:ring-1 focus:ring-theme-accent focus:border-theme-accent outline-none"
      />
      <Show when={showSuggestions()}>
        <div class="absolute z-50 w-full mt-1 bg-theme-surface shadow-[var(--shadow-md)] border border-theme-border rounded-[var(--radius-sm)] max-h-48 overflow-y-auto">
          <For each={suggestions()}>
            {(target) => (
              <button
                type="button"
                class="w-full text-left px-3 py-2 hover:bg-theme-accent/20 text-theme-text-primary text-sm"
                onMouseDown={() => selectTarget(target)}
              >
                <span class="font-medium">{target.primary_name}</span>
                <Show when={target.object_type}>
                  <span class="text-theme-text-secondary ml-2">({target.object_type})</span>
                </Show>
                <Show when={target.match_source}>
                  <span class="text-theme-accent text-xs ml-2">
                    matched: {target.match_source}
                  </span>
                </Show>
                <Show when={target.similarity_score < 1.0}>
                  <span class="text-theme-text-secondary text-xs ml-1">
                    ~{Math.round(target.similarity_score * 100)}%
                  </span>
                </Show>
              </button>
            )}
          </For>
        </div>
      </Show>
    </div>
  );
};

export default SearchBar;
