import { Component, For, Show, createSignal, createMemo, onMount } from "solid-js";
import { api } from "../../api/client";
import { showToast } from "../Toast";
import { useAuth } from "../AuthProvider";
import type { FilenameCandidateResponse } from "../../types";

const methodLabel = (c: FilenameCandidateResponse) => {
  switch (c.method) {
    case "simbad": return "SIMBAD confirmed";
    case "alias_match": return "Exact match";
    case "common_name": return "Common name";
    case "space_insert": return "Catalog match";
    case "simbad_new": return "SIMBAD (new target)";
    case "trigram": return `${Math.round(c.confidence * 100)}% match`;
    case "none": return "No match";
    default: return c.method;
  }
};

export const UnresolvedFilesTab: Component = () => {
  const { isAdmin } = useAuth();
  const [candidates, setCandidates] = createSignal<FilenameCandidateResponse[]>([]);
  const [detecting, setDetecting] = createSignal(false);
  const [expandedId, setExpandedId] = createSignal<string | null>(null);
  const [confirmId, setConfirmId] = createSignal<string | null>(null);
  const [filter, setFilter] = createSignal<"all" | "has_suggestion" | "no_suggestion">("all");

  const refresh = async () => {
    try {
      const c = await api.getFilenameCandidates("pending");
      setCandidates(c);
    } catch {
      // Non-blocking
    }
  };

  onMount(refresh);

  const resolved = createMemo(() => {
    const all = candidates().filter((c) => c.extracted_name !== null);
    if (filter() === "has_suggestion") return all.filter((c) => c.suggested_target_id !== null);
    if (filter() === "no_suggestion") return all.filter((c) => c.suggested_target_id === null);
    return all;
  });

  const unresolvable = createMemo(() =>
    candidates().filter((c) => c.extracted_name === null),
  );

  const unresolvableDirs = createMemo(() => {
    const dirMap = new Map<string, string[]>();
    for (const c of unresolvable()) {
      for (const fp of c.file_paths) {
        const dir = fp.replace(/[/\\][^/\\]*$/, "") || ".";
        if (!dirMap.has(dir)) dirMap.set(dir, []);
        dirMap.get(dir)!.push(fp);
      }
    }
    return Array.from(dirMap.entries()).sort((a, b) => a[0].localeCompare(b[0]));
  });

  const unresolvableFileCount = createMemo(() =>
    unresolvable().reduce((sum, c) => sum + c.file_count, 0),
  );

  const handleDetect = async () => {
    setDetecting(true);
    try {
      await api.triggerFilenameDetection();
      showToast("Filename detection started - results will appear shortly");
      setTimeout(refresh, 5000);
    } catch {
      showToast("Failed to start detection", "error");
    } finally {
      setDetecting(false);
    }
  };

  const handleAccept = async (c: FilenameCandidateResponse) => {
    setConfirmId(null);
    try {
      const createNew = c.method === "simbad_new";
      await api.acceptFilenameCandidate(c.id, c.suggested_target_id ?? undefined, createNew);
      showToast(`Assigned ${c.file_count} file(s) via "${c.extracted_name}"`);
      await refresh();
    } catch {
      showToast("Assignment failed", "error");
    }
  };

  const handleDismiss = async (c: FilenameCandidateResponse) => {
    try {
      await api.dismissFilenameCandidate(c.id);
      setCandidates((prev) => prev.filter((x) => x.id !== c.id));
    } catch {
      showToast("Dismiss failed", "error");
    }
  };

  return (
    <div class="space-y-4">
      {/* Top controls */}
      <div class="flex items-center justify-between gap-3 flex-wrap">
        <div class="flex items-center gap-3">
          <select
            value={filter()}
            onChange={(e) => setFilter(e.currentTarget.value as typeof filter extends () => infer T ? T : never)}
            class="px-2 py-1.5 text-sm bg-theme-surface border border-theme-border rounded-[var(--radius-sm)] text-theme-text-primary"
          >
            <option value="all">All</option>
            <option value="has_suggestion">Has suggestion</option>
            <option value="no_suggestion">No suggestion</option>
          </select>
          <span class="text-sm text-theme-text-secondary">
            <span class="tabular-nums">{resolved().length}</span> resolved
            {" \u00b7 "}
            <span class="tabular-nums">{unresolvable().length}</span> unresolvable
          </span>
        </div>
        <Show when={isAdmin()}>
          <button
            onClick={handleDetect}
            disabled={detecting()}
            class="px-3 py-1.5 border border-theme-border-em text-theme-text-secondary rounded text-sm disabled:opacity-50 hover:text-theme-text-primary hover:border-theme-accent transition-colors"
          >
            {detecting() ? "Detecting..." : "Run Detection"}
          </button>
        </Show>
      </div>

      {/* Resolved candidates */}
      <Show
        when={resolved().length > 0}
        fallback={<p class="text-sm text-theme-text-secondary">No resolved candidates. Run detection to scan filenames.</p>}
      >
        <div class="space-y-2">
          <For each={resolved()}>
            {(c) => (
              <div class="p-3 bg-theme-base/50 border border-theme-border rounded-[var(--radius-sm)]">
                <div class="flex items-center justify-between">
                  <div class="flex-1 min-w-0">
                    <span class="text-theme-text-primary text-sm font-medium">{c.extracted_name}</span>
                    <span class="text-xs text-theme-text-secondary bg-theme-surface border border-theme-border rounded px-1.5 py-0.5 ml-2">
                      {methodLabel(c)}
                    </span>
                    <Show
                      when={c.suggested_target_name}
                      fallback={<span class="text-theme-text-secondary text-xs italic ml-2">No target match</span>}
                    >
                      <span class="text-theme-text-secondary text-xs mx-2">&rarr;</span>
                      <span class="text-theme-accent text-sm">{c.suggested_target_name}</span>
                    </Show>
                    <span class="text-xs text-theme-text-secondary ml-2 tabular-nums">{c.file_count} file{c.file_count !== 1 ? "s" : ""}</span>
                  </div>
                  <div class="flex items-center gap-2">
                    <Show when={isAdmin()}>
                      <Show when={c.suggested_target_id || c.method === "simbad_new"}>
                        <button
                          onClick={() => setConfirmId(c.id)}
                          class="px-2 py-1 text-xs border border-theme-accent/50 text-theme-accent rounded-[var(--radius-sm)] hover:bg-theme-accent/10 transition-colors"
                        >
                          Assign
                        </button>
                      </Show>
                      <button
                        onClick={() => handleDismiss(c)}
                        class="px-2 py-1 text-xs border border-theme-border text-theme-text-secondary rounded hover:text-theme-text-primary transition-colors"
                      >
                        Dismiss
                      </button>
                    </Show>
                    <button
                      onClick={() => setExpandedId(expandedId() === c.id ? null : c.id)}
                      class="px-1 py-1 text-xs text-theme-text-secondary hover:text-theme-text-primary transition-colors"
                    >
                      {expandedId() === c.id ? "\u25B2" : "\u25BC"}
                    </button>
                  </div>
                </div>

                {/* Confirmation modal */}
                <Show when={confirmId() === c.id}>
                  <div class="w-full mt-2 bg-theme-accent/10 border border-theme-accent/30 rounded-[var(--radius-md)] p-3 space-y-2">
                    <p class="text-sm text-theme-accent font-medium">
                      Assign {c.file_count} file(s) from "{c.extracted_name}" to "{c.suggested_target_name}"?
                    </p>
                    <p class="text-xs text-theme-text-secondary">
                      Matching files will be linked to the target. This can be reverted later.
                    </p>
                    <div class="flex gap-2 pt-1">
                      <button
                        onClick={() => handleAccept(c)}
                        class="px-3 py-1.5 bg-theme-accent text-white rounded text-xs font-medium hover:opacity-90 transition-opacity"
                      >
                        Yes, assign
                      </button>
                      <button
                        onClick={() => setConfirmId(null)}
                        class="px-3 py-1.5 border border-theme-border-em text-theme-text-secondary rounded text-xs hover:text-theme-text-primary transition-colors"
                      >
                        Cancel
                      </button>
                    </div>
                  </div>
                </Show>

                {/* Expanded file list */}
                <Show when={expandedId() === c.id}>
                  <div class="mt-2 pt-2 border-t border-theme-border space-y-1">
                    <For each={c.file_paths}>
                      {(fp) => (
                        <p class="text-xs text-theme-text-secondary font-mono truncate" title={fp}>{fp}</p>
                      )}
                    </For>
                  </div>
                </Show>
              </div>
            )}
          </For>
        </div>
      </Show>

      {/* Unresolvable files */}
      <Show when={unresolvable().length > 0}>
        <details class="bg-theme-base/50 border border-theme-border rounded-[var(--radius-sm)]">
          <summary class="px-3 py-2 text-sm text-theme-text-secondary cursor-pointer hover:text-theme-text-primary transition-colors">
            Unresolvable files — <span class="tabular-nums">{unresolvableFileCount()}</span> file{unresolvableFileCount() !== 1 ? "s" : ""} in <span class="tabular-nums">{unresolvableDirs().length}</span> director{unresolvableDirs().length !== 1 ? "ies" : "y"}
          </summary>
          <div class="px-3 pb-3 space-y-2">
            <For each={unresolvable()}>
              {(c) => (
                <div class="p-2 border border-theme-border rounded-[var(--radius-sm)]">
                  <div class="flex items-center justify-between">
                    <div class="flex-1 min-w-0">
                      <span class="text-xs text-theme-text-secondary font-mono truncate block" title={c.file_paths[0]}>
                        {c.file_paths[0]?.replace(/[/\\][^/\\]*$/, "") || "unknown"}
                      </span>
                      <span class="text-xs text-theme-text-secondary tabular-nums">{c.file_count} file{c.file_count !== 1 ? "s" : ""}</span>
                    </div>
                    <div class="flex items-center gap-2">
                      <Show when={isAdmin()}>
                        <button
                          onClick={() => handleDismiss(c)}
                          class="px-2 py-1 text-xs border border-theme-border text-theme-text-secondary rounded hover:text-theme-text-primary transition-colors"
                        >
                          Dismiss
                        </button>
                      </Show>
                      <button
                        onClick={() => setExpandedId(expandedId() === c.id ? null : c.id)}
                        class="px-1 py-1 text-xs text-theme-text-secondary hover:text-theme-text-primary transition-colors"
                      >
                        {expandedId() === c.id ? "\u25B2" : "\u25BC"}
                      </button>
                    </div>
                  </div>
                  <Show when={expandedId() === c.id}>
                    <div class="mt-2 pt-2 border-t border-theme-border space-y-1">
                      <For each={c.file_paths}>
                        {(fp) => (
                          <p class="text-xs text-theme-text-secondary font-mono truncate" title={fp}>{fp}</p>
                        )}
                      </For>
                    </div>
                  </Show>
                </div>
              )}
            </For>
          </div>
        </details>
      </Show>
    </div>
  );
};
