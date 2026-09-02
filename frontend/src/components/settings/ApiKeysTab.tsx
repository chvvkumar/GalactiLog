import { Component, Show, createSignal, onMount } from "solid-js";
import { apiKeysApi, type ApiKey, type CreatedApiKey } from "../../api/apiKeys";
import { ApiError } from "../../api/unwrap";
import { showToast } from "../Toast";
import { formatDate, relativeTime } from "../../utils/dateTime";
import { useSettingsContext } from "../SettingsProvider";
import HelpPopover from "../HelpPopover";
import DataTable, { type DataTableColumn } from "../DataTable";
import Button from "../ui/Button";

const CopyIcon: Component = () => (
  <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
    <rect x="9" y="9" width="13" height="13" rx="2" ry="2" />
    <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
  </svg>
);

export const ApiKeysTab: Component = () => {
  const settingsCtx = useSettingsContext();
  const [keys, setKeys] = createSignal<ApiKey[]>([]);
  const [loading, setLoading] = createSignal(true);
  const [error, setError] = createSignal<string | null>(null);
  const [newName, setNewName] = createSignal("");
  const [newCanWrite, setNewCanWrite] = createSignal(false);
  const [creating, setCreating] = createSignal(false);
  const [created, setCreated] = createSignal<CreatedApiKey | null>(null);
  const [confirmRevokeId, setConfirmRevokeId] = createSignal<string | null>(null);

  const refresh = async () => {
    try {
      setKeys(await apiKeysApi.list());
      setError(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to load API keys");
    } finally {
      setLoading(false);
    }
  };

  onMount(refresh);

  const handleCreate = async (e: Event) => {
    e.preventDefault();
    setCreating(true);
    try {
      const key = await apiKeysApi.create(newName().trim(), newCanWrite());
      setCreated(key);
      setNewName("");
      setNewCanWrite(false);
      await refresh();
    } catch (err) {
      showToast(err instanceof ApiError ? err.message : "Failed to create API key", "error");
    } finally {
      setCreating(false);
    }
  };

  const handleRevoke = async (k: ApiKey) => {
    setConfirmRevokeId(null);
    try {
      await apiKeysApi.revoke(k.id);
      showToast(`Key "${k.name}" revoked`);
      await refresh();
    } catch (err) {
      showToast(err instanceof ApiError ? err.message : "Failed to revoke API key", "error");
    }
  };

  const copyCreatedKey = async () => {
    const k = created();
    if (!k) return;
    try {
      await navigator.clipboard.writeText(k.key);
      showToast("API key copied to clipboard");
    } catch {
      showToast("Could not copy to clipboard", "error");
    }
  };

  const isRevoked = (k: ApiKey) => k.revoked_at !== null;
  const dim = (k: ApiKey) => (isRevoked(k) ? "opacity-50" : "");

  const columns: DataTableColumn<ApiKey>[] = [
    {
      key: "name",
      label: "Name",
      alwaysVisible: true,
      render: (k) => <span class={`font-medium ${dim(k)}`}>{k.name}</span>,
    },
    {
      key: "prefix",
      label: "Key",
      alwaysVisible: true,
      render: (k) => (
        <span class={`font-mono text-xs text-theme-text-secondary ${dim(k)}`}>{k.prefix}...</span>
      ),
    },
    {
      key: "permission",
      label: "Permission",
      alwaysVisible: true,
      render: (k) => (
        <span
          class={`text-xs px-1.5 py-0.5 rounded ${dim(k)} ${
            k.can_write
              ? "bg-theme-warning/15 text-theme-warning border border-theme-warning/30"
              : "bg-theme-info/15 text-theme-info border border-theme-info/30"
          }`}
        >
          {k.can_write ? "Read + act" : "Read"}
        </span>
      ),
    },
    {
      key: "created",
      label: "Created",
      alwaysVisible: true,
      render: (k) => (
        <span class={`text-xs text-theme-text-secondary ${dim(k)}`}>
          {formatDate(k.created_at, settingsCtx.timezone())}
        </span>
      ),
    },
    {
      key: "last_used",
      label: "Last used",
      alwaysVisible: true,
      render: (k) => (
        <span
          class={`text-xs text-theme-text-secondary ${dim(k)}`}
          title={k.last_used_at ? formatDate(k.last_used_at, settingsCtx.timezone()) : undefined}
        >
          {relativeTime(k.last_used_at)}
        </span>
      ),
    },
    {
      key: "status",
      label: "Status",
      alwaysVisible: true,
      render: (k) => (
        <Show
          when={isRevoked(k)}
          fallback={<span class="text-xs text-theme-success">Active</span>}
        >
          <span class="text-xs text-theme-text-tertiary">
            Revoked {formatDate(k.revoked_at!, settingsCtx.timezone())}
          </span>
        </Show>
      ),
    },
    {
      key: "actions",
      label: "Actions",
      align: "right",
      alwaysVisible: true,
      render: (k) => (
        <Show when={!isRevoked(k)}>
          <div class="flex justify-end">
            <Button variant="danger" size="sm" onClick={() => setConfirmRevokeId(k.id)}>
              Revoke
            </Button>
          </div>
          <Show when={confirmRevokeId() === k.id}>
            <div class="mt-2 bg-theme-error/20 border border-theme-error/50 rounded-[var(--radius-md)] p-3 space-y-2 text-left">
              <p class="text-sm text-theme-error font-medium">Revoke "{k.name}"?</p>
              <p class="text-xs text-theme-error/70">
                Anything using this key stops working immediately. This cannot be undone; issue a new key instead.
              </p>
              <div class="flex gap-2 pt-1">
                <Button variant="danger" size="sm" onClick={() => handleRevoke(k)}>
                  Yes, revoke
                </Button>
                <Button variant="secondary" size="sm" onClick={() => setConfirmRevokeId(null)}>
                  Cancel
                </Button>
              </div>
            </div>
          </Show>
        </Show>
      ),
    },
  ];

  return (
    <div class="space-y-4">
      <div class="flex items-center gap-2">
        <h2 class="text-base font-medium text-theme-text-primary">API Keys</h2>
        <HelpPopover title="API Keys">
          <p>API keys authenticate programs against the public API at /api/v1, separately from browser logins. Send one as a bearer token: <code>Authorization: Bearer glg_...</code></p>
          <p>A read key can list targets, sessions, frames, and statistics. A "Read + act" key can additionally trigger scans, send coordinates to NINA or Stellarium, and write notes.</p>
          <p>The full key is shown once, at creation. Store it where the calling program can read it; if it is lost, revoke the key and create another.</p>
          <p>Revoking takes effect immediately. Revoked keys stay listed so you can see what existed and when it was last used.</p>
        </HelpPopover>
      </div>

      <Show when={created()}>
        {(k) => (
          <div class="bg-theme-warning/10 border border-theme-warning/40 rounded-[var(--radius-md)] p-4 space-y-3">
            <div class="flex items-start justify-between gap-3">
              <div>
                <p class="text-sm font-medium text-theme-warning">Copy your key now</p>
                <p class="text-xs text-theme-text-secondary mt-1">
                  This is the only time the full key for "{k().name}" is shown. It is stored hashed and cannot be displayed again.
                </p>
              </div>
              <Button variant="secondary" size="sm" onClick={() => setCreated(null)}>
                Dismiss
              </Button>
            </div>
            <div class="flex items-center gap-2 bg-theme-base border border-theme-border rounded-[var(--radius-sm)] px-3 py-2">
              <code class="flex-1 font-mono text-xs text-theme-text-primary overflow-x-auto whitespace-nowrap">
                {k().key}
              </code>
              <button
                onClick={copyCreatedKey}
                class="cursor-pointer text-theme-text-secondary hover:text-theme-text-primary shrink-0"
                title="Copy key"
                aria-label="Copy key"
              >
                <CopyIcon />
              </button>
            </div>
          </div>
        )}
      </Show>

      <form
        onSubmit={handleCreate}
        class="bg-theme-elevated border border-theme-border rounded-[var(--radius-md)] p-4 flex flex-wrap items-end gap-4"
      >
        <div class="flex-1 min-w-48">
          <label for="apikey-name" class="block text-xs text-theme-text-secondary mb-1">
            Name
          </label>
          <input
            id="apikey-name"
            type="text"
            value={newName()}
            onInput={(e) => setNewName(e.currentTarget.value)}
            placeholder="Observatory dashboard"
            class="w-full bg-theme-base border border-theme-border rounded px-2 py-1.5 text-sm text-theme-text-primary"
            required
          />
        </div>
        <label class="flex items-center gap-2 text-sm text-theme-text-primary pb-1.5 cursor-pointer">
          <input
            type="checkbox"
            checked={newCanWrite()}
            onChange={(e) => setNewCanWrite(e.currentTarget.checked)}
            class="accent-[var(--color-accent)]"
          />
          Allow actions
          <span class="text-xs text-theme-text-secondary">(scans, pointing, notes)</span>
        </label>
        <Button type="submit" size="sm" class="mb-0.5" disabled={creating() || !newName().trim()}>
          {creating() ? "Creating..." : "Create Key"}
        </Button>
      </form>

      <div class="bg-theme-surface border border-theme-border rounded overflow-hidden">
        <DataTable
          columns={columns}
          rows={keys()}
          rowKey={(k) => k.id}
          loading={loading()}
          error={error()}
          emptyMessage="No API keys yet"
        />
      </div>
    </div>
  );
};

export default ApiKeysTab;
