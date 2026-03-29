import { Component } from "solid-js";
import { A } from "@solidjs/router";

const NavBar: Component = () => {

  return (
    <header class="sticky top-0 z-30 bg-theme-surface backdrop-blur-sm border-b border-theme-border px-6 py-3 flex items-center gap-6">
      <h1 class="text-theme-text-primary font-bold tracking-tight text-lg whitespace-nowrap">GalactiLog</h1>
      <nav class="flex gap-4">
        <A
          href="/"
          class="text-sm text-theme-text-secondary hover:text-theme-text-primary transition-colors"
          activeClass="text-theme-text-primary font-medium bg-theme-elevated rounded-[var(--radius-sm)] px-2.5 py-1"
          end
        >
          Dashboard
        </A>
        <A
          href="/statistics"
          class="text-sm text-theme-text-secondary hover:text-theme-text-primary transition-colors"
          activeClass="text-theme-text-primary font-medium bg-theme-elevated rounded-[var(--radius-sm)] px-2.5 py-1"
        >
          Statistics
        </A>
        <A
          href="/settings"
          class="text-theme-text-secondary hover:text-theme-text-primary transition-colors text-sm"
          activeClass="text-theme-text-primary font-medium bg-theme-elevated rounded-[var(--radius-sm)] px-2.5 py-1"
        >
          Settings
        </A>
      </nav>
      <div class="ml-auto">
        <a
          href="https://github.com/chvvkumar/GalactiLog"
          target="_blank"
          rel="noopener noreferrer"
          class="text-theme-text-secondary hover:text-theme-text-primary transition-colors"
          title="GitHub"
        >
          <svg width="20" height="20" viewBox="0 0 16 16" fill="currentColor">
            <path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27s1.36.09 2 .27c1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.01 8.01 0 0 0 16 8c0-4.42-3.58-8-8-8z"/>
          </svg>
        </a>
      </div>
    </header>
  );
};

export default NavBar;
