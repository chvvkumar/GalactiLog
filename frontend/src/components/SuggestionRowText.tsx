import { Component, Show } from "solid-js";
import type { TargetSearchResultFuzzy } from "../api/types";

// Inner text of a target-search suggestion row: primary name, object type,
// the matched alias when it adds information beyond the primary name, and
// an approximate-match hint for non-exact scores.
const SuggestionRowText: Component<{ target: TargetSearchResultFuzzy }> = (props) => {
  const matched = () => {
    const m = props.target.match_source;
    return m && !props.target.primary_name.toLowerCase().includes(m.toLowerCase()) ? m : null;
  };
  return (
    <>
      <span class="font-medium">{props.target.primary_name}</span>
      <Show when={props.target.object_type}>
        <span class="text-xs text-theme-text-secondary ml-2">{props.target.object_type}</span>
      </Show>
      <Show when={matched()}>
        <span class="text-xs text-theme-text-secondary ml-2">matched {matched()}</span>
      </Show>
      <Show when={props.target.similarity_score < 1.0}>
        <span class="text-xs text-theme-text-secondary ml-1">
          ~{Math.round(props.target.similarity_score * 100)}%
        </span>
      </Show>
    </>
  );
};

export default SuggestionRowText;
