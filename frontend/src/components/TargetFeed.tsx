import { Component, Show } from "solid-js";
import { useCatalog } from "../store/catalog";
import TargetTable from "./TargetTable";

const TargetFeed: Component = () => {
  const { targetData } = useCatalog();

  return (
    <div class="p-4">
      <Show when={targetData.loading}>
        <div class="text-center text-theme-text-secondary py-8">Loading targets...</div>
      </Show>
      <Show when={targetData.error}>
        <div class="text-center text-theme-error py-8">
          Failed to load targets: {String(targetData.error)}
        </div>
      </Show>
      <Show when={targetData()}>
        {(data) => (
          <Show
            when={data().targets.length > 0}
            fallback={<div class="text-center text-theme-text-secondary py-8">No targets match your filters</div>}
          >
            <TargetTable targets={data().targets} />
          </Show>
        )}
      </Show>
    </div>
  );
};

export default TargetFeed;
