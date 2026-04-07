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

/** Extract a common directory from file paths for use as row title. */
const commonDir = (paths: string[]): string => {
  if (!paths.length) return "Unknown";
  // Find the longest common directory prefix
  const dirs = paths.map((p) => p.replace(/[/\\][^/\\]*$/, ""));
  if (dirs.length === 1) return dirs[0];
  let common = dirs[0];
  for (let i = 1; i < dirs.length; i++) {
    while (common && !dirs[i].startsWith(common)) {
      common = common.replace(/[/\\][^/\\]*$/, "");
    }
  }
  return common || dirs[0];
};

export const UnresolvedFilesTab: Component = () => {
  const { isAdmin } = useAuth();
  const [pending, setPending] = createSignal<FilenameCandidateResponse[]>([]);
  const [accepted, setAccepted] = createSignal<FilenameCandidateResponse[]>([]);
  const [detecting, setDetecting] = createSignal(false);
  const [expandedId, setExpandedId] = createSignal<string | null>(null);
  const [confirmId, setConfirmId] = createSignal<string | null>(null);
  const [confirmRevertId, setConfirmRevertId] = createSignal<string | null>(null);
  const [filter, setFilter] = createSignal<"all" | "has_suggestion" | "no_suggestion">("all");

  const refresh = async () => {
    try {
      const [p, a] = await Promise.all([
        api.getFilenameCandidates("pending"),
        api.getFilenameCandidates("accepted"),
      ]);
      setPending(p);
      setAccepted(a);
    } catch {
      // Non-blocking
    }
  };

  onMount(refresh);

  const resolved = createMemo(() => {
    const all = pending().filter((c) => c.extracted_name !== null);
    if (filter() === "has_suggestion") return all.filter((c) => c.suggested_target_id !== null);
    if (filter() === "no_suggestion") return all.filter((c) => c.suggested_target_id === null);
    return all;
  });

  const unresolvable = createMemo(() =>
    pending().filter((c) => c.extracted_name === null),
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
      setPending((prev) => prev.filter((x) => x.id !== c.id));
    } catch {
      showToast("Dismiss failed", "error");
    }
  };

  const handleRevert = async (c: FilenameCandidateResponse) => {
    setConfirmRevertId(null);
    try {
      await api.revertFilenameCandidate(c.id);
      showToast(`Reverted "${c.extracted_name}"`);
      await refresh();
    } catch {
      showToast("Revert failed", "error");
    }
  };

  const toggleExpand = (id: string) => {
    setExpandedId((prev) => (prev === id ? null : id));
  };

  /** Render a single candidate row (used in both pending and accepted sections). */
  const CandidateRow: Component<{
    c: FilenameCandidateResponse;
    mode: "pending" | "accepted";
  }> = (props) => {
    const c = props.c;
    const dir = createMemo(() => commonDir(c.file_paths));
    const isExpanded = () => expandedId() === c.id;

    return (
      <div
        class={`border border-theme-border rounded-[var(--radius-sm)] transition-all duration-150 ${
          isExpanded()
            ? "bg-theme-elevated border-l-[3px] border-l-theme-accent"
            : "bg-theme-base/50 border-l-[3px] border-l-transparent hover:border-l-theme-accent/50 hover:bg-theme-hover"
        }`}
      >
        {/* Header row -- clickable to expand */}
        <div
          class="flex items-center justify-between p-3 cursor-pointer select-none"
          onClick={() => toggleExpand(c.id)}
        >
          <div class="flex-1 min-w-0">
            {/* Title: path for context */}
            <div class="text-xs text-theme-text-secondary font-mono truncate mb-1" title={dir()}>
              {dir()}
            </div>
            {/* Extracted name + method badge + target suggestion */}
            <div class="flex items-center gap-2 flex-wrap">
              <Show when={c.extracted_name}>
                <span class="text-theme-text-primary text-sm font-medium">{c.extracted_name}</span>
              </Show>
              <Show when={!c.extracted_name}>
                <span class="text-theme-text-secondary/60 text-sm italic">No name extracted</span>
              </Show>
              <span class="text-xs text-theme-text-secondary bg-theme-surface border border-theme-border rounded px-1.5 py-0.5">
                {methodLabel(c)}
              </span>
              <Show when={c.suggested_target_name}>
                <span class="text-theme-text-secondary text-xs">&rarr;</span>
                <span class="text-theme-accent text-sm">{c.suggested_target_name}</span>
              </Show>
              <Show when={c.extracted_name && !c.suggested_target_id && c.method !== "simbad_new"}>
                <span class="text-theme-text-secondary/60 text-xs italic">No target match</span>
              </Show>
              <span class="text-xs text-theme-text-secondary tabular-nums">
                {c.file_count} file{c.file_count !== 1 ? "s" : ""}
              </span>
            </div>
          </div>

          {/* Actions */}
          <div class="flex items-center gap-2 ml-3 shrink-0" onClick={(e) => e.stopPropagation()}>
            <Show when={isAdmin()}>
              <Show when={props.mode === "pending"}>
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
              <Show when={props.mode === "accepted"}>
                <button
                  onClick={() => setConfirmRevertId(c.id)}
                  class="px-2 py-1 text-xs border border-theme-border text-theme-text-secondary rounded-[var(--radius-sm)] hover:text-theme-text-primary transition-colors"
                >
                  Revert
                </button>
              </Show>
            </Show>
          </div>
        </div>

        {/* Confirmation modal -- assign */}
        <Show when={confirmId() === c.id}>
          <div class="mx-3 mb-3 bg-theme-accent/10 border border-theme-accent/30 rounded-[var(--radius-md)] p-3 space-y-2">
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

        {/* Confirmation modal -- revert */}
        <Show when={confirmRevertId() === c.id}>
          <div class="mx-3 mb-3 bg-theme-warning/10 border border-theme-warning/30 rounded-[var(--radius-md)] p-3 space-y-2">
            <p class="text-sm text-theme-warning font-medium">Revert "{c.extracted_name}"?</p>
            <p class="text-xs text-theme-text-secondary">
              Files will be unlinked from "{c.suggested_target_name}" and returned to pending.
            </p>
            <div class="flex gap-2 pt-1">
              <button
                onClick={() => handleRevert(c)}
                class="px-3 py-1.5 bg-theme-warning text-white rounded text-xs font-medium hover:opacity-90 transition-opacity"
              >
                Yes, revert
              </button>
              <button
                onClick={() => setConfirmRevertId(null)}
                class="px-3 py-1.5 border border-theme-border-em text-theme-text-secondary rounded text-xs hover:text-theme-text-primary transition-colors"
              >
                Cancel
              </button>
            </div>
          </div>
        </Show>

        {/* Expanded file list */}
        <Show when={isExpanded()}>
          <div class="mx-3 mb-3 pt-2 border-t border-theme-border max-h-60 overflow-y-auto space-y-0.5">
            <For each={c.file_paths}>
              {(fp) => (
                <p class="text-xs text-theme-text-secondary font-mono truncate py-0.5" title={fp}>{fp}</p>
              )}
            </For>
          </div>
        </Show>
      </div>
    );
  };

  return (
    <div class="space-y-6">
      {/* ── Pending Section ── */}
      <div class="space-y-3">
        <div class="flex items-center justify-between gap-3 flex-wrap">
          <div class="flex items-center gap-3">
            <h4 class="text-theme-text-primary text-sm font-medium">Pending</h4>
            <select
              value={filter()}
              onChange={(e) => setFilter(e.currentTarget.value as typeof filter extends () => infer T ? T : never)}
              class="px-2 py-1 text-xs bg-theme-surface border border-theme-border rounded-[var(--radius-sm)] text-theme-text-primary"
            >
              <option value="all">All</option>
              <option value="has_suggestion">Has suggestion</option>
              <option value="no_suggestion">No suggestion</option>
            </select>
            <span class="text-xs text-theme-text-secondary tabular-nums">
              {resolved().length + unresolvable().length} pending
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

        <Show
          when={resolved().length > 0 || unresolvable().length > 0}
          fallback={<p class="text-sm text-theme-text-secondary">No pending candidates. Run detection to scan filenames.</p>}
        >
          <div class="space-y-2">
            <For each={resolved()}>
              {(c) => <CandidateRow c={c} mode="pending" />}
            </For>
            <For each={unresolvable()}>
              {(c) => <CandidateRow c={c} mode="pending" />}
            </For>
          </div>
        </Show>
      </div>

      {/* ── Resolved Section ── */}
      <div class="space-y-3">
        <div class="flex items-center justify-between gap-3 flex-wrap">
          <div class="flex items-center gap-3">
            <h4 class="text-theme-text-primary text-sm font-medium">Resolved</h4>
            <span class="text-xs text-theme-text-secondary tabular-nums">
              {accepted().length} resolved
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

        <Show
          when={accepted().length > 0}
          fallback={<p class="text-sm text-theme-text-secondary">No resolved files yet.</p>}
        >
          <div class="space-y-2">
            <For each={accepted()}>
              {(c) => <CandidateRow c={c} mode="accepted" />}
            </For>
          </div>
        </Show>
      </div>
    </div>
  );
};
