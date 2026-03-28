import { Component, For } from "solid-js";
import type { SessionSummary } from "../types";
import FilterBadges from "./FilterBadges";

function formatHours(seconds: number): string {
  return (seconds / 3600).toFixed(1) + "h";
}

const SessionTable: Component<{
  sessions: SessionSummary[];
  onDeepDive: (date: string) => void;
}> = (props) => {
  return (
    <div class="border-t border-theme-border mt-2">
      <table class="w-full text-xs">
        <thead>
          <tr class="text-theme-text-secondary border-b border-theme-border">
            <th class="text-left py-1.5 px-2 font-normal">Date</th>
            <th class="text-right py-1.5 px-2 font-normal">Frames</th>
            <th class="text-right py-1.5 px-2 font-normal">Integration</th>
            <th class="text-left py-1.5 px-2 font-normal">Filters</th>
            <th class="py-1.5 px-2"></th>
          </tr>
        </thead>
        <tbody>
          <For each={props.sessions}>
            {(session) => (
              <tr class="border-b border-theme-border/50 hover:bg-theme-surface/50">
                <td class="py-1.5 px-2 text-theme-text-primary">{session.session_date}</td>
                <td class="py-1.5 px-2 text-right text-theme-text-primary">{session.frame_count}</td>
                <td class="py-1.5 px-2 text-right text-theme-text-primary">{formatHours(session.integration_seconds)}</td>
                <td class="py-1.5 px-2">
                  <FilterBadges distribution={Object.fromEntries(session.filters_used.map(f => [f, 0]))} compact />
                </td>
                <td class="py-1.5 px-2 text-right">
                  <button
                    onClick={() => props.onDeepDive(session.session_date)}
                    class="text-theme-accent hover:underline text-[11px]"
                  >
                    Deep Dive
                  </button>
                </td>
              </tr>
            )}
          </For>
        </tbody>
      </table>
    </div>
  );
};

export default SessionTable;
