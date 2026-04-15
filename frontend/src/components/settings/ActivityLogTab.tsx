import { Component, createSignal, onMount, Show } from "solid-js";
import { api } from "../../api/client";
import { useAuth } from "../AuthProvider";
import { showToast } from "../Toast";

const ActivityLogTab: Component = () => {
  const { isAdmin } = useAuth();
  const [retentionDays, setRetentionDays] = createSignal(90);
  const [saving, setSaving] = createSignal(false);
  const [clearing, setClearing] = createSignal(false);
  const [showClearConfirm, setShowClearConfirm] = createSignal(false);
  const [loading, setLoading] = createSignal(true);

  onMount(async () => {
    try {
      const s = await api.getActivitySettings();
      setRetentionDays(s.activity_retention_days);
    } catch { /* ignore */ } finally {
      setLoading(false);
    }
  });

  const handleSave = async () => {
    if (saving()) return;
    setSaving(true);
    try {
      const res = await api.setActivitySettings({ retention_days: retentionDays() });
      setRetentionDays(res.activity_retention_days);
      showToast("Retention setting saved", "success", 3000);
    } catch {
      showToast("Failed to save retention setting", "error", 0);
    } finally {
      setSaving(false);
    }
  };

  const handleClear = async () => {
    if (clearing()) return;
    setShowClearConfirm(false);
    setClearing(true);
    try {
      await api.clearActivityLog();
      showToast("Activity log cleared", "success", 3000);
    } catch {
      showToast("Failed to clear activity log", "error", 0);
    } finally {
      setClearing(false);
    }
  };

  return (
    <div class="space-y-4">
      <div class="bg-theme-surface border border-theme-border rounded-[var(--radius-md)] shadow-[var(--shadow-sm)] p-4 space-y-4">
        <h3 class="text-theme-text-primary font-medium">Activity Log</h3>

        <Show when={loading()}>
          <p class="text-xs text-theme-text-secondary">Loading...</p>
        </Show>

        <Show when={!loading()}>
          <div class="space-y-3">
            <div class="flex items-center gap-3">
              <label class="text-sm text-theme-text-secondary w-40 flex-shrink-0">
                Retention (days)
              </label>
              <input
                type="number"
                min={1}
                max={3650}
                value={retentionDays()}
                onInput={(e) => {
                  const v = parseInt(e.currentTarget.value, 10);
                  if (!isNaN(v) && v >= 1 && v <= 3650) setRetentionDays(v);
                }}
                class="w-24 px-2 py-1 text-sm bg-theme-base border border-theme-border rounded text-theme-text-primary focus:outline-none focus:border-theme-accent tabular-nums"
              />
              <button
                onClick={handleSave}
                disabled={saving() || !isAdmin()}
                class="px-3 py-1.5 bg-theme-accent/15 text-theme-accent border border-theme-accent/30 rounded text-sm disabled:opacity-50 hover:bg-theme-accent/25 transition-colors"
              >
                {saving() ? "Saving..." : "Save"}
              </button>
            </div>
            <p class="text-xs text-theme-text-secondary">
              Events older than this many days are deleted by the nightly pruner. Min 1, max 3650.
            </p>
          </div>

          <Show when={isAdmin()}>
            <div class="border-t border-theme-border pt-4 space-y-2">
              <Show when={!showClearConfirm()}>
                <button
                  onClick={() => setShowClearConfirm(true)}
                  disabled={clearing()}
                  class="px-3 py-1.5 border border-theme-error/50 text-theme-error rounded text-sm disabled:opacity-50 hover:bg-theme-error/20 transition-colors"
                >
                  Clear activity log
                </button>
              </Show>
              <Show when={showClearConfirm()}>
                <div class="bg-theme-error/10 border border-theme-error/40 rounded-[var(--radius-md)] p-3 space-y-2">
                  <p class="text-sm text-theme-error font-medium">Clear all activity?</p>
                  <p class="text-xs text-theme-error/70">
                    This permanently deletes all activity log entries. The action cannot be undone.
                  </p>
                  <div class="flex gap-2 pt-1">
                    <button
                      onClick={handleClear}
                      class="px-3 py-1.5 bg-theme-error text-theme-text-primary rounded text-xs font-medium hover:opacity-90 transition-colors"
                    >
                      Yes, clear all
                    </button>
                    <button
                      onClick={() => setShowClearConfirm(false)}
                      class="px-3 py-1.5 border border-theme-border-em text-theme-text-secondary rounded text-xs hover:text-theme-text-primary transition-colors"
                    >
                      Cancel
                    </button>
                  </div>
                </div>
              </Show>
            </div>
          </Show>
        </Show>
      </div>
    </div>
  );
};

export default ActivityLogTab;
