import { Component, Show, createSignal } from "solid-js";
import { A, useNavigate, useLocation } from "@solidjs/router";
import { sidebarOpen, setSidebarOpen } from "../pages/DashboardPage";
import { useAuth } from "./AuthProvider";

const NavBar: Component = () => {
  const { user, logout, isAdmin } = useAuth();
  const navigate = useNavigate();
  const [menuOpen, setMenuOpen] = createSignal(false);

  const handleLogout = async () => {
    await logout();
    navigate("/login");
  };

  return (
    <header class="sticky top-0 z-30 bg-theme-surface backdrop-blur-sm border-b border-theme-border px-4 lg:px-6 py-3 flex items-center gap-4 lg:gap-6">
      <A href="/" class="flex items-center gap-2 no-underline">
        <img src="/logo-transparent.png" alt="GalactiLog logo" class="h-7 w-7" />
        <h1 class="text-theme-text-primary font-bold tracking-tight text-lg whitespace-nowrap">GalactiLog</h1>
      </A>

      {/* Desktop nav */}
      <nav class="hidden lg:flex gap-4">
        <A
          href="/"
          class="text-sm text-theme-text-secondary hover:text-theme-text-primary transition-colors"
          activeClass="text-theme-text-primary font-medium bg-theme-elevated rounded-[var(--radius-sm)] px-2.5 py-1"
          end
        >
          Dashboard
        </A>
        <A
          href="/mosaics"
          class="text-sm text-theme-text-secondary hover:text-theme-text-primary transition-colors"
          activeClass="text-theme-text-primary font-medium bg-theme-elevated rounded-[var(--radius-sm)] px-2.5 py-1"
        >
          Mosaics
        </A>
        <A
          href="/statistics"
          class="text-sm text-theme-text-secondary hover:text-theme-text-primary transition-colors"
          activeClass="text-theme-text-primary font-medium bg-theme-elevated rounded-[var(--radius-sm)] px-2.5 py-1"
        >
          Statistics
        </A>
        <A
          href="/analysis"
          class="text-sm text-theme-text-secondary hover:text-theme-text-primary transition-colors"
          activeClass="text-theme-text-primary font-medium bg-theme-elevated rounded-[var(--radius-sm)] px-2.5 py-1"
        >
          Analysis
        </A>
        <A
          href="/settings"
          class="text-theme-text-secondary hover:text-theme-text-primary transition-colors text-sm"
          activeClass="text-theme-text-primary font-medium bg-theme-elevated rounded-[var(--radius-sm)] px-2.5 py-1"
        >
          Settings
        </A>
      </nav>

      <div class="ml-auto flex items-center gap-3">
        <Show when={user()}>
          <span class="text-xs text-theme-text-secondary hidden sm:inline">
            {user()!.username}
            <Show when={!isAdmin()}>{" "}(viewer)</Show>
          </span>
          <button
            onClick={handleLogout}
            class="text-xs text-theme-text-secondary hover:text-theme-text-primary transition-colors hidden sm:inline"
          >
            Sign out
          </button>
        </Show>
        <a
          href="https://github.com/chvvkumar/GalactiLog"
          target="_blank"
          rel="noopener noreferrer"
          class="text-theme-text-secondary hover:text-theme-text-primary transition-colors hidden sm:inline"
          title="GitHub"
        >
          <svg width="20" height="20" viewBox="0 0 16 16" fill="currentColor">
            <path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27s1.36.09 2 .27c1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.01 8.01 0 0 0 16 8c0-4.42-3.58-8-8-8z"/>
          </svg>
        </a>

        {/* Filter button -- visible < lg on dashboard only */}
        <Show when={useLocation().pathname === "/"}>
          <button
            class="lg:hidden p-1 text-theme-text-secondary hover:text-theme-text-primary transition-colors"
            onClick={() => setSidebarOpen(!sidebarOpen())}
            aria-label="Toggle filters"
          >
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <polygon points="22 3 2 3 10 12.46 10 19 14 21 14 12.46 22 3" />
            </svg>
          </button>
        </Show>

        {/* Hamburger button -- visible < lg */}
        <button
          class="lg:hidden p-1 text-theme-text-secondary hover:text-theme-text-primary transition-colors"
          onClick={() => setMenuOpen(!menuOpen())}
          aria-label="Toggle menu"
        >
          <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
            <Show when={!menuOpen()} fallback={
              <>{/* X icon */}
                <line x1="6" y1="6" x2="18" y2="18" />
                <line x1="6" y1="18" x2="18" y2="6" />
              </>
            }>
              {/* Hamburger icon */}
              <line x1="4" y1="6" x2="20" y2="6" />
              <line x1="4" y1="12" x2="20" y2="12" />
              <line x1="4" y1="18" x2="20" y2="18" />
            </Show>
          </svg>
        </button>
      </div>

      {/* Mobile dropdown menu */}
      <Show when={menuOpen()}>
        <div class="absolute top-full left-0 right-0 glass-popover bg-theme-surface border-b border-theme-border shadow-[var(--shadow-md)] lg:hidden z-40">
          <nav class="flex flex-col p-4 gap-2">
            <A
              href="/"
              class="text-sm text-theme-text-secondary hover:text-theme-text-primary transition-colors py-2 px-3 rounded-[var(--radius-sm)]"
              activeClass="text-theme-text-primary font-medium bg-theme-elevated"
              end
              onClick={() => setMenuOpen(false)}
            >
              Dashboard
            </A>
            <A
              href="/mosaics"
              class="text-sm text-theme-text-secondary hover:text-theme-text-primary transition-colors py-2 px-3 rounded-[var(--radius-sm)]"
              activeClass="text-theme-text-primary font-medium bg-theme-elevated"
              onClick={() => setMenuOpen(false)}
            >
              Mosaics
            </A>
            <A
              href="/statistics"
              class="text-sm text-theme-text-secondary hover:text-theme-text-primary transition-colors py-2 px-3 rounded-[var(--radius-sm)]"
              activeClass="text-theme-text-primary font-medium bg-theme-elevated"
              onClick={() => setMenuOpen(false)}
            >
              Statistics
            </A>
            <A
              href="/analysis"
              class="text-sm text-theme-text-secondary hover:text-theme-text-primary transition-colors py-2 px-3 rounded-[var(--radius-sm)]"
              activeClass="text-theme-text-primary font-medium bg-theme-elevated"
              onClick={() => setMenuOpen(false)}
            >
              Analysis
            </A>
            <A
              href="/settings"
              class="text-sm text-theme-text-secondary hover:text-theme-text-primary transition-colors py-2 px-3 rounded-[var(--radius-sm)]"
              activeClass="text-theme-text-primary font-medium bg-theme-elevated"
              onClick={() => setMenuOpen(false)}
            >
              Settings
            </A>
            <Show when={user()}>
              <div class="border-t border-theme-border mt-2 pt-2 flex items-center justify-between px-3">
                <span class="text-xs text-theme-text-secondary">
                  {user()!.username}
                  <Show when={!isAdmin()}>{" "}(viewer)</Show>
                </span>
                <button
                  onClick={() => { handleLogout(); setMenuOpen(false); }}
                  class="text-xs text-theme-text-secondary hover:text-theme-text-primary transition-colors"
                >
                  Sign out
                </button>
              </div>
            </Show>
          </nav>
        </div>
      </Show>
    </header>
  );
};

export default NavBar;
