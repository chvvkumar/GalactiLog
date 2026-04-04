import { Component, createSignal, For, Show } from "solid-js";
import { api } from "../api/client";
import { useDashboardFilters } from "./DashboardFilterProvider";
import { debounce } from "../utils/debounce";
import type { TargetSearchResultFuzzy } from "../types";

const SearchBar: Component = () => {
  const { updateFilter } = useDashboardFilters();
  const [query, setQuery] = createSignal("");
  const [suggestions, setSuggestions] = createSignal<TargetSearchResultFuzzy[]>([]);
  const [showSuggestions, setShowSuggestions] = createSignal(false);
  const [activeIndex, setActiveIndex] = createSignal(-1);

  const fetchSuggestions = debounce(async (value: string) => {
    try {
      const results = await api.searchTargets(value);
      setSuggestions(results);
      setShowSuggestions(results.length > 0);
    } catch {
      setSuggestions([]);
    }
    updateFilter("searchQuery", value);
  }, 300);

  const onInput = (value: string) => {
    setQuery(value);
    setActiveIndex(-1);
    if (value.length < 2) {
      setSuggestions([]);
      setShowSuggestions(false);
      updateFilter("searchQuery", value);
      return;
    }
    fetchSuggestions(value);
  };

  const onKeyDown = (e: KeyboardEvent) => {
    const list = suggestions();
    if (!showSuggestions() || list.length === 0) return;

    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActiveIndex((i) => (i < list.length - 1 ? i + 1 : 0));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActiveIndex((i) => (i > 0 ? i - 1 : list.length - 1));
    } else if (e.key === "Enter" && activeIndex() >= 0) {
      e.preventDefault();
      selectTarget(list[activeIndex()]);
    } else if (e.key === "Escape") {
      setShowSuggestions(false);
      setActiveIndex(-1);
    }
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
        onKeyDown={onKeyDown}
        onFocus={() => suggestions().length > 0 && setShowSuggestions(true)}
        onBlur={() => setTimeout(() => setShowSuggestions(false), 200)}
        placeholder="M31, NGC 7000..."
        class="w-full px-3 py-2 bg-theme-input border border-theme-border rounded-[var(--radius-sm)] text-sm text-theme-text-primary placeholder:text-theme-text-tertiary focus:ring-1 focus:ring-theme-accent focus:border-theme-accent outline-none"
      />
      <Show when={showSuggestions()}>
        <div class="absolute z-50 w-full mt-1 bg-theme-surface shadow-[var(--shadow-md)] border border-theme-border rounded-[var(--radius-sm)] max-h-48 overflow-y-auto">
          <For each={suggestions()}>
            {(target, i) => (
              <button
                type="button"
                class={`w-full text-left px-3 py-2 text-theme-text-primary text-sm ${activeIndex() === i() ? "bg-theme-accent/20" : "hover:bg-theme-accent/20"}`}
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
