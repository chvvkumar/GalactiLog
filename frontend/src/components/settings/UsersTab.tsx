import { Component, Show, createSignal, onMount } from "solid-js";
import { apiClient } from "../../api/generated/client";
import { unwrap, ApiError } from "../../api/unwrap";
import { showToast } from "../Toast";
import { useAuth } from "../AuthProvider";
import type { UserAccount } from "../../api/types";
import { formatDate } from "../../utils/dateTime";
import { useSettingsContext } from "../SettingsProvider";
import HelpPopover from "../HelpPopover";
import DataTable, { type DataTableColumn } from "../DataTable";
import Button from "../ui/Button";

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
      setUsers(await apiClient.GET("/api/auth/users").then(unwrap));
    } catch {
      showToast("Failed to load users", "error");
    }
  };

  onMount(refresh);

  const handleCreate = async (e: Event) => {
    e.preventDefault();
    setCreating(true);
    try {
      await apiClient
        .POST("/api/auth/users", {
          body: { username: newUsername(), password: newPassword(), role: newRole() },
        })
        .then(unwrap);
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
      await apiClient
        .PUT("/api/auth/users/{user_id}", {
          params: { path: { user_id: u.id } },
          body: { is_active: !u.is_active },
        })
        .then(unwrap);
      await refresh();
    } catch (err) {
      const msg = err instanceof ApiError && err.status === 400 ? "Cannot deactivate yourself" : "Failed to update user";
      showToast(msg, "error");
    }
  };

  const handleChangeRole = async (u: UserAccount) => {
    const newRole = u.role === "admin" ? "viewer" : "admin";
    try {
      await apiClient
        .PUT("/api/auth/users/{user_id}", {
          params: { path: { user_id: u.id } },
          body: { role: newRole },
        })
        .then(unwrap);
      await refresh();
    } catch (err) {
      const msg = err instanceof ApiError && err.status === 400 ? "Cannot change your own role" : "Failed to update user";
      showToast(msg, "error");
    }
  };

  const handleDelete = async (u: UserAccount) => {
    setConfirmDeleteId(null);
    try {
      await apiClient
        .DELETE("/api/auth/users/{user_id}", { params: { path: { user_id: u.id } } })
        .then(unwrap);
      showToast(`User "${u.username}" deleted`);
      await refresh();
    } catch (err) {
      const msg = err instanceof ApiError && err.status === 400 ? "Cannot delete yourself" : "Failed to delete user";
      showToast(msg, "error");
    }
  };

  const isSelf = (u: UserAccount) => u.id === currentUser()?.id;

  const columns: DataTableColumn<UserAccount>[] = [
    {
      key: "username",
      label: "Username",
      alwaysVisible: true,
      render: (u) => (
        <>
          {u.username}
          <Show when={isSelf(u)}>
            <span class="ml-1.5 text-xs text-theme-text-secondary">(you)</span>
          </Show>
        </>
      ),
    },
    {
      key: "role",
      label: "Role",
      alwaysVisible: true,
      render: (u) => (
        <span
          class={`text-xs px-1.5 py-0.5 rounded ${
            u.role === "admin"
              ? "bg-theme-accent/20 text-theme-accent"
              : "bg-theme-elevated text-theme-text-secondary"
          }`}
        >
          {u.role}
        </span>
      ),
    },
    {
      key: "status",
      label: "Status",
      alwaysVisible: true,
      render: (u) => (
        <span class={`text-xs ${u.is_active ? "text-green-400" : "text-red-400"}`}>
          {u.is_active ? "Active" : "Disabled"}
        </span>
      ),
    },
    {
      key: "created",
      label: "Created",
      alwaysVisible: true,
      render: (u) => (
        <span class="text-theme-text-secondary text-xs">
          {formatDate(u.created_at, settingsCtx.timezone())}
        </span>
      ),
    },
    {
      key: "actions",
      label: "Actions",
      align: "right",
      alwaysVisible: true,
      render: (u) => (
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
            <Button variant="danger" size="sm" onClick={() => setConfirmDeleteId(u.id)}>
              Delete
            </Button>
          </div>
          <Show when={confirmDeleteId() === u.id}>
            <div class="mt-2 bg-theme-error/20 border border-theme-error/50 rounded-[var(--radius-md)] p-3 space-y-2 text-left">
              <p class="text-sm text-theme-error font-medium">Delete "{u.username}"?</p>
              <p class="text-xs text-theme-error/70">This cannot be undone. All data associated with this user will be removed.</p>
              <div class="flex gap-2 pt-1">
                <Button variant="danger" size="sm" onClick={() => handleDelete(u)}>
                  Yes, delete
                </Button>
                <Button variant="secondary" size="sm" onClick={() => setConfirmDeleteId(null)}>
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
      <div class="flex items-center justify-between">
        <div class="flex items-center gap-2">
          <h2 class="text-base font-medium text-theme-text-primary">User Accounts</h2>
          <HelpPopover title="User Accounts">
            <p>Lists the user accounts on this GalactiLog instance. Admins can create accounts, promote or demote between viewer and admin, disable access, reset passwords, and delete users.</p>
            <p>Viewers can browse the catalog, targets, sessions, and mosaics but cannot change settings, trigger scans, or edit data. Admins have full access.</p>
            <p>You cannot delete your own account. The account marked "(you)" is the one making the request.</p>
            <p>Example: create a viewer account for a collaborator who should see statistics without being able to modify configuration.</p>
          </HelpPopover>
        </div>
        <Button size="sm" onClick={() => setShowCreate(!showCreate())}>
          {showCreate() ? "Cancel" : "Add User"}
        </Button>
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
          <Button type="submit" size="sm" disabled={creating()}>
            {creating() ? "Creating..." : "Create User"}
          </Button>
        </form>
      </Show>

      <div class="bg-theme-surface border border-theme-border rounded overflow-hidden">
        <DataTable
          columns={columns}
          rows={users()}
          rowKey={(u) => u.id}
          emptyMessage="No users found"
        />
      </div>
    </div>
  );
};
