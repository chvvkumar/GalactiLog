import { Component, For } from "solid-js";

const IngestHistory: Component<{ history: { date: string; files_added: number }[] }> = (props) => {
  return (
    <div class="bg-theme-surface border border-theme-border rounded-[var(--radius-md)] shadow-[var(--shadow-sm)] p-4 space-y-2">
      <h3 class="text-theme-text-primary font-medium text-sm">Ingest History</h3>
      <div class="max-h-48 overflow-y-auto">
        <For each={props.history}>
          {(entry) => (
            <div class="flex justify-between text-xs py-1 border-b border-theme-border/30">
              <span class="text-theme-text-primary">{entry.date}</span>
              <span class="text-theme-text-secondary">+{entry.files_added} files</span>
            </div>
          )}
        </For>
      </div>
    </div>
  );
};

export default IngestHistory;
