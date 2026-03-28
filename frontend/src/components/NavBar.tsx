import { Component, Show } from "solid-js";
import { A } from "@solidjs/router";
import { useCatalog } from "../store/catalog";

function formatHours(seconds: number): string {
  return (seconds / 3600).toFixed(1) + "h";
}

const NavBar: Component = () => {
  const { targetData } = useCatalog();

  return (
    <header class="border-b border-theme-border px-6 py-3 flex items-center gap-6">
      <h1 class="text-theme-text-primary font-bold text-lg whitespace-nowrap">GalactiLog</h1>
      <nav class="flex gap-4">
        <A
          href="/"
          class="text-sm text-theme-text-secondary hover:text-theme-text-primary transition-colors"
          activeClass="text-theme-text-primary font-medium"
          end
        >
          Dashboard
        </A>
        <A
          href="/admin"
          class="text-sm text-theme-text-secondary hover:text-theme-text-primary transition-colors"
          activeClass="text-theme-text-primary font-medium"
        >
          Admin & Stats
        </A>
        <A
          href="/settings"
          class="text-theme-text-secondary hover:text-theme-text-primary transition-colors text-sm"
          activeClass="text-theme-text-primary font-medium"
        >
          Settings
        </A>
      </nav>
      <Show when={targetData()}>
        {(data) => (
          <div class="ml-auto flex gap-5 text-sm items-end">
            <span class="text-theme-text-secondary">
              Integration <span class="text-theme-text-primary font-semibold">{formatHours(data().aggregates.total_integration_seconds)}</span>
            </span>
            <span class="text-theme-text-secondary">
              Targets <span class="text-theme-text-primary font-semibold">{String(data().aggregates.target_count)}</span>
            </span>
            <span class="text-theme-text-secondary">
              Frames <span class="text-theme-text-primary font-semibold">{data().aggregates.total_frames.toLocaleString()}</span>
            </span>
            <span class="text-[10px] text-theme-text-tertiary italic">filtered</span>
          </div>
        )}
      </Show>
    </header>
  );
};

export default NavBar;
