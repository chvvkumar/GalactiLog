import { Component, createSignal, Show } from "solid-js";
import { useAuth } from "../components/AuthProvider";
import { showToast } from "../components/Toast";

const LoginPage: Component = () => {
  const { login } = useAuth();
  const [username, setUsername] = createSignal("");
  const [password, setPassword] = createSignal("");
  const [error, setError] = createSignal("");
  const [submitting, setSubmitting] = createSignal(false);

  const handleSubmit = async (e: Event) => {
    e.preventDefault();
    setError("");
    setSubmitting(true);
    try {
      await login(username(), password());
      showToast(`Welcome, ${username()}`);
      window.location.href = "/";
    } catch (err: any) {
      setError(err?.message || "Login failed");
      setSubmitting(false);
    }
  };

  return (
    <div class="min-h-screen bg-theme-base flex items-center justify-center px-4">
      <div class="w-full max-w-sm bg-theme-surface border border-theme-border rounded-[var(--radius-md)] shadow-[var(--shadow-sm)] p-8 space-y-6">
        <div class="flex flex-col items-center gap-2">
          <img src="/logo-transparent.png" alt="GalactiLog logo" class="h-12 w-12" />
          <h1 class="text-theme-text-primary font-bold text-xl tracking-tight">GalactiLog</h1>
        </div>

        <Show when={error()}>
          <div class="bg-theme-error/20 border border-theme-error/50 rounded-[var(--radius-sm)] px-3 py-2 text-sm text-theme-error">
            {error()}
          </div>
        </Show>

        <form onSubmit={handleSubmit} class="space-y-4">
          <div class="space-y-1.5">
            <label class="block text-sm text-theme-text-secondary" for="username">Username</label>
            <input
              id="username"
              type="text"
              autocomplete="username"
              value={username()}
              onInput={(e) => setUsername(e.currentTarget.value)}
              class="w-full px-3 py-2 bg-theme-input border border-theme-border rounded-[var(--radius-sm)] text-sm text-theme-text-primary focus:ring-1 focus:ring-theme-accent focus:border-theme-accent outline-none"
              required
            />
          </div>
          <div class="space-y-1.5">
            <label class="block text-sm text-theme-text-secondary" for="password">Password</label>
            <input
              id="password"
              type="password"
              autocomplete="current-password"
              value={password()}
              onInput={(e) => setPassword(e.currentTarget.value)}
              class="w-full px-3 py-2 bg-theme-input border border-theme-border rounded-[var(--radius-sm)] text-sm text-theme-text-primary focus:ring-1 focus:ring-theme-accent focus:border-theme-accent outline-none"
              required
            />
          </div>
          <button
            type="submit"
            disabled={submitting()}
            class="w-full py-1.5 bg-theme-accent/15 text-theme-accent border border-theme-accent/30 rounded text-sm font-medium disabled:opacity-50 hover:bg-theme-accent/25 transition-colors"
          >
            {submitting() ? "Signing in..." : "Sign in"}
          </button>
        </form>
      </div>
    </div>
  );
};

export default LoginPage;
