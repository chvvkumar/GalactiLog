import { createContext, createSignal, useContext, onMount, onCleanup, Show, type ParentProps, type Component } from "solid-js";
import { api } from "../api/client";
import { ApiError } from "../api/client";
import type { AuthUser } from "../types";

interface AuthContextValue {
  user: () => AuthUser | null;
  loading: () => boolean;
  login: (username: string, password: string, remember?: boolean) => Promise<void>;
  logout: () => Promise<void>;
  refreshUser: () => Promise<void>;
  isAdmin: () => boolean;
}

const AuthContext = createContext<AuthContextValue>();

const API_BASE = import.meta.env.VITE_API_URL || "/api";

/** Returns true when /api/health responds 200. */
async function checkHealth(): Promise<boolean> {
  try {
    const r = await fetch(`${API_BASE}/health`, { cache: "no-store" });
    return r.ok;
  } catch {
    return false;
  }
}

const StartupScreen: Component<{ onReady: () => void }> = (props) => {
  const [dots, setDots] = createSignal("");
  const [elapsed, setElapsed] = createSignal(0);

  const dotTimer = setInterval(() => {
    setDots((d) => (d.length >= 3 ? "" : d + "."));
  }, 500);

  const elapsedTimer = setInterval(() => {
    setElapsed((e) => e + 1);
  }, 1000);

  const healthPoll = setInterval(async () => {
    if (await checkHealth()) props.onReady();
  }, 2000);

  onCleanup(() => {
    clearInterval(dotTimer);
    clearInterval(elapsedTimer);
    clearInterval(healthPoll);
  });

  return (
    <div class="fixed inset-0 flex flex-col items-center justify-center gap-6"
         style="background: #0a0a1a; color: #a0a0b8; font-family: 'Inter', sans-serif;">
      <div style="font-size: 1.5rem; font-weight: 600; color: #e0e0f0;">
        GalactiLog
      </div>
      <div style="font-size: 0.875rem;">
        Server is starting up{dots()}
      </div>
      <div style="width: 200px; height: 3px; background: #1a1a2e; border-radius: 2px; overflow: hidden;">
        <div style="height: 100%; background: #4a6cf7; border-radius: 2px; animation: pulse 1.5s ease-in-out infinite;" />
      </div>
      <div style="font-size: 0.75rem; color: #606078;">
        Waiting for database and services ({elapsed()}s)
      </div>
      <style>{`
        @keyframes pulse {
          0%, 100% { width: 20%; opacity: 0.5; }
          50% { width: 80%; opacity: 1; }
        }
      `}</style>
    </div>
  );
};

export const AuthProvider: Component<ParentProps> = (props) => {
  const [user, setUser] = createSignal<AuthUser | null>(null);
  const [loading, setLoading] = createSignal(true);
  const [serverStarting, setServerStarting] = createSignal(false);

  const refreshUser = async () => {
    try {
      const me = await api.getMe();
      setUser(me);
    } catch (e) {
      setUser(null);
      throw e;
    }
  };

  const login = async (username: string, password: string, remember?: boolean) => {
    await api.login(username, password, remember ?? false);
    await refreshUser();
  };

  const logout = async () => {
    await api.logout();
    setUser(null);
  };

  const isAdmin = () => user()?.role === "admin";

  const initAuth = async () => {
    // Clean up stale token from prior auth implementation
    try {
      if (localStorage.getItem("token") !== null) {
        localStorage.removeItem("token");
      }
    } catch {
      // localStorage unavailable (private browsing, etc.)
    }
    try {
      // Timeout the initial auth check so a hanging upstream (nginx
      // connected but backend not ready) falls through to the startup
      // screen instead of showing "Loading..." forever.
      const timeout = new Promise<never>((_, reject) =>
        setTimeout(() => reject(new Error("timeout")), 5000),
      );
      await Promise.race([refreshUser(), timeout]);
    } catch (e) {
      // 502/503/504 = nginx is up but backend isn't ready yet
      // Network error (not ApiError) = nothing is listening yet
      // Timeout = upstream accepted connection but never responded
      // "Session expired" / "Unauthorized" = server is up, user just isn't authenticated
      const isAuthError =
        e instanceof Error &&
        (e.message === "Session expired" || e.message === "Unauthorized");
      const serverDown =
        !isAuthError && (
          !(e instanceof ApiError) ||
          e.status === 502 || e.status === 503 || e.status === 504
        );
      if (serverDown) {
        setServerStarting(true);
        return;
      }
      // Auth errors fall through -- user will be redirected to login by ProtectedRoute
    }
    setLoading(false);
  };

  const onServerReady = async () => {
    setServerStarting(false);
    try {
      await refreshUser();
    } catch {
      // Server is up but user not authenticated -- that's fine
    }
    setLoading(false);
  };

  onMount(initAuth);

  return (
    <Show when={!serverStarting()} fallback={<StartupScreen onReady={onServerReady} />}>
      <AuthContext.Provider value={{ user, loading, login, logout, refreshUser, isAdmin }}>
        {props.children}
      </AuthContext.Provider>
    </Show>
  );
};

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
