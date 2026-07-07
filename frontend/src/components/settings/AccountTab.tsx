import { Component, Show, createSignal } from "solid-js";
import { apiClient } from "../../api/generated/client";
import { unwrap, ApiError } from "../../api/unwrap";
import { showToast } from "../Toast";
import { useAuth } from "../AuthProvider";
import { getErrorMessage } from "../../utils/errors";

export const AccountTab: Component = () => {
  const { user } = useAuth();
  const [current, setCurrent] = createSignal("");
  const [next, setNext] = createSignal("");
  const [confirm, setConfirm] = createSignal("");
  const [saving, setSaving] = createSignal(false);

  const inputClass =
    "w-full px-2.5 py-1.5 text-sm bg-theme-base border border-theme-border rounded-[var(--radius-sm)] text-theme-text-primary placeholder:text-theme-text-secondary/50 focus:outline-none focus:border-theme-accent";

  const reset = () => {
    setCurrent("");
    setNext("");
    setConfirm("");
  };

  const handleSubmit = async (e: Event) => {
    e.preventDefault();
    if (saving()) return;
    if (!current() || !next()) {
      showToast("Enter your current and new password", "error");
      return;
    }
    if (next() !== confirm()) {
      showToast("New password and confirmation do not match", "error");
      return;
    }
    if (next() === current()) {
      showToast("New password must differ from the current one", "error");
      return;
    }
    setSaving(true);
    try {
      await apiClient
        .PUT("/api/auth/password", {
          body: { current_password: current(), new_password: next() },
        })
        .then(unwrap);
      showToast("Password changed");
      reset();
    } catch (err) {
      const msg =
        err instanceof ApiError && err.status === 400
          ? "Current password is incorrect"
          : getErrorMessage(err, "Failed to change password");
      showToast(msg, "error", 5000);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div class="rounded-[var(--radius-sm)] bg-theme-elevated border border-theme-border-em p-4 space-y-4">
      <div>
        <h2 class="text-sm font-semibold text-theme-text-primary">Change Password</h2>
        <Show when={user()}>
          <p class="text-xs text-theme-text-secondary mt-1">
            Signed in as <span class="text-theme-text-primary">{user()!.username}</span>
          </p>
        </Show>
      </div>
      <form class="space-y-3 max-w-sm" onSubmit={handleSubmit}>
        <div class="space-y-1">
          <label class="text-xs text-theme-text-secondary">Current password</label>
          <input
            type="password"
            autocomplete="current-password"
            class={inputClass}
            value={current()}
            onInput={(e) => setCurrent(e.currentTarget.value)}
          />
        </div>
        <div class="space-y-1">
          <label class="text-xs text-theme-text-secondary">New password</label>
          <input
            type="password"
            autocomplete="new-password"
            class={inputClass}
            value={next()}
            onInput={(e) => setNext(e.currentTarget.value)}
          />
        </div>
        <div class="space-y-1">
          <label class="text-xs text-theme-text-secondary">Confirm new password</label>
          <input
            type="password"
            autocomplete="new-password"
            class={inputClass}
            value={confirm()}
            onInput={(e) => setConfirm(e.currentTarget.value)}
          />
        </div>
        <button
          type="submit"
          disabled={saving()}
          class="px-4 py-1.5 bg-theme-accent/15 text-theme-accent border border-theme-accent/30 rounded text-sm font-medium hover:bg-theme-accent/25 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {saving() ? "Saving..." : "Change Password"}
        </button>
      </form>
    </div>
  );
};

export default AccountTab;
