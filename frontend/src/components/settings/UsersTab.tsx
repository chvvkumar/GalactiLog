import { Component, For, Show, createSignal, onMount } from "solid-js";
import { api, ApiError } from "../../api/client";
import { showToast } from "../Toast";
import { useAuth } from "../AuthProvider";
import type { UserAccount } from "../../types";
import { formatDate } from "../../utils/dateTime";
import { useSettingsContext } from "../SettingsProvider";

export const UsersTab: Component = () => {
  const { user: currentUser } = useAuth();
  const settingsCtx = useSettingsContext();
  const [users, setUsers] = createSignal<UserAccount[]>([]);
  const [showCreate, setShowCreate] = createSignal(false);
  const [newUsername, setNewUsername] = createSignal("");
  const [newPassword, setNewPassword] = createSignal("");
  const [newRole, setNewRole] = createSignal<"admin" | "viewer">("viewer");
  const [creating, setCreating] = createSignal(false);
  const [confirmDeleteId, setConfirmDeleteId] = createSignal<string | null>(null);

  const refresh = async () => {
    try {
      setUsers(await api.getUsers());
    } catch {
      showToast("Failed to load users", "error");
    }
  };

  onMount(refresh);

  const handleCreate = async (e: Event) => {
    e.preventDefault();
    setCreating(true);
    try {
      await api.createUser(newUsername(), newPassword(), newRole());
      showToast(`User "${newUsername()}" created`);
      setNewUsername("");
      setNewPassword("");
      setNewRole("viewer");
      setShowCreate(false);
      await refresh();
    } catch (err) {
      const msg = err instanceof ApiError && err.status === 409 ? "Username already exists" : "Failed to create user";
      showToast(msg, "error");
    } finally {
      setCreating(false);
    }
  };

  const handleToggleActive = async (u: UserAccount) => {
    try {
      await api.updateUser(u.id, { is_active: !u.is_active });
      await refresh();
    } catch (err) {
      const msg = err instanceof ApiError && err.status === 400 ? "Cannot deactivate yourself" : "Failed to update user";
      showToast(msg, "error");
    }
  };

  const handleChangeRole = async (u: UserAccount) => {
    const newRole = u.role === "admin" ? "viewer" : "admin";
    try {
      await api.updateUser(u.id, { role: newRole });
      await refresh();
    } catch (err) {
      const msg = err instanceof ApiError && err.status === 400 ? "Cannot change your own role" : "Failed to update user";
      showToast(msg, "error");
    }
  };

  const handleDelete = async (u: UserAccount) => {
    setConfirmDeleteId(null);
    try {
      await api.deleteUser(u.id);
      showToast(`User "${u.username}" deleted`);
      await refresh();
    } catch (err) {
      const msg = err instanceof ApiError && err.status === 400 ? "Cannot delete yourself" : "Failed to delete user";
      showToast(msg, "error");
    }
  };

  const isSelf = (u: UserAccount) => u.id === currentUser()?.id;

  return (
    <div class="space-y-4">
      <div class="flex items-center justify-between">
        <h2 class="text-base font-medium text-theme-text-primary">User Accounts</h2>
        <button
          onClick={() => setShowCreate(!showCreate())}
          class="px-3 py-1.5 text-xs bg-theme-accent/15 text-theme-accent border border-theme-accent/30 rounded font-medium hover:bg-theme-accent/25 transition-colors"
        >
          {showCreate() ? "Cancel" : "Add User"}
        </button>
      </div>

      <Show when={showCreate()}>
        <form onSubmit={handleCreate} class="bg-theme-elevated border border-theme-border rounded p-4 space-y-3">
          <div class="grid grid-cols-3 gap-3">
            <div>
              <label class="block text-xs text-theme-text-secondary mb-1">Username</label>
              <input
                type="text"
                value={newUsername()}
                onInput={(e) => setNewUsername(e.currentTarget.value)}
                class="w-full bg-theme-base border border-theme-border rounded px-2 py-1.5 text-sm text-theme-text-primary"
                required
              />
            </div>
            <div>
              <label class="block text-xs text-theme-text-secondary mb-1">Password (min 8 chars)</label>
              <input
                type="password"
                value={newPassword()}
                onInput={(e) => setNewPassword(e.currentTarget.value)}
                class="w-full bg-theme-base border border-theme-border rounded px-2 py-1.5 text-sm text-theme-text-primary"
                minLength={8}
                required
              />
            </div>
            <div>
              <label class="block text-xs text-theme-text-secondary mb-1">Role</label>
              <select
                value={newRole()}
                onChange={(e) => setNewRole(e.currentTarget.value as "admin" | "viewer")}
                class="w-full bg-theme-base border border-theme-border rounded px-2 py-1.5 text-sm text-theme-text-primary"
              >
                <option value="viewer">Viewer</option>
                <option value="admin">Admin</option>
              </select>
            </div>
          </div>
          <button
            type="submit"
            disabled={creating()}
            class="px-3 py-1.5 text-xs bg-theme-accent/15 text-theme-accent border border-theme-accent/30 rounded font-medium hover:bg-theme-accent/25 transition-colors disabled:opacity-50"
          >
            {creating() ? "Creating..." : "Create User"}
          </button>
        </form>
      </Show>

      <div class="bg-theme-surface border border-theme-border rounded overflow-hidden">
        <table class="w-full text-sm">
          <thead>
            <tr class="border-b border-theme-border text-theme-text-secondary text-xs">
              <th class="text-left px-4 py-2 font-medium">Username</th>
              <th class="text-left px-4 py-2 font-medium">Role</th>
              <th class="text-left px-4 py-2 font-medium">Status</th>
              <th class="text-left px-4 py-2 font-medium">Created</th>
              <th class="text-right px-4 py-2 font-medium">Actions</th>
            </tr>
          </thead>
          <tbody>
            <For each={users()}>
              {(u) => (
                <tr class="border-b border-theme-border last:border-b-0">
                  <td class="px-4 py-2.5 text-theme-text-primary">
                    {u.username}
                    <Show when={isSelf(u)}>
                      <span class="ml-1.5 text-xs text-theme-text-secondary">(you)</span>
                    </Show>
                  </td>
                  <td class="px-4 py-2.5">
                    <span class={`text-xs px-1.5 py-0.5 rounded ${
                      u.role === "admin"
                        ? "bg-theme-accent/20 text-theme-accent"
                        : "bg-theme-elevated text-theme-text-secondary"
                    }`}>
                      {u.role}
                    </span>
                  </td>
                  <td class="px-4 py-2.5">
                    <span class={`text-xs ${u.is_active ? "text-green-400" : "text-red-400"}`}>
                      {u.is_active ? "Active" : "Disabled"}
                    </span>
                  </td>
                  <td class="px-4 py-2.5 text-theme-text-secondary text-xs">
                    {formatDate(u.created_at, settingsCtx.timezone())}
                  </td>
                  <td class="px-4 py-2.5 text-right">
                    <Show when={!isSelf(u)}>
                      <div class="flex gap-2 justify-end">
                        <button
                          onClick={() => handleChangeRole(u)}
                          class="text-xs text-theme-text-secondary hover:text-theme-text-primary transition-colors"
                          title={`Change to ${u.role === "admin" ? "viewer" : "admin"}`}
                        >
                          {u.role === "admin" ? "Demote" : "Promote"}
                        </button>
                        <button
                          onClick={() => handleToggleActive(u)}
                          class="text-xs text-theme-text-secondary hover:text-theme-text-primary transition-colors"
                        >
                          {u.is_active ? "Disable" : "Enable"}
                        </button>
                        <button
                          onClick={() => setConfirmDeleteId(u.id)}
                          class="text-xs text-red-400 hover:text-red-300 transition-colors"
                        >
                          Delete
                        </button>
                      </div>
                      <Show when={confirmDeleteId() === u.id}>
                        <div class="mt-2 bg-theme-error/20 border border-theme-error/50 rounded-[var(--radius-md)] p-3 space-y-2">
                          <p class="text-sm text-theme-error font-medium">Delete "{u.username}"?</p>
                          <p class="text-xs text-theme-error/70">This cannot be undone. All data associated with this user will be removed.</p>
                          <div class="flex gap-2 pt-1">
                            <button
                              onClick={() => handleDelete(u)}
                              class="px-3 py-1.5 bg-theme-error text-white rounded text-xs font-medium hover:opacity-90 transition-opacity"
                            >
                              Yes, delete
                            </button>
                            <button
                              onClick={() => setConfirmDeleteId(null)}
                              class="px-3 py-1.5 border border-theme-border-em text-theme-text-secondary rounded text-xs hover:text-theme-text-primary transition-colors"
                            >
                              Cancel
                            </button>
                          </div>
                        </div>
                      </Show>
                    </Show>
                  </td>
                </tr>
              )}
            </For>
          </tbody>
        </table>
        <Show when={users().length === 0}>
          <p class="text-center text-theme-text-secondary text-sm py-6">No users found</p>
        </Show>
      </div>
    </div>
  );
};
