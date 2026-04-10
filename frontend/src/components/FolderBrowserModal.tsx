import { Component, createSignal, createEffect, onCleanup, Show, For } from "solid-js";
import { createStore, produce } from "solid-js/store";
import { scanFilters } from "../api/scanFilters";
import type { BrowseEntry } from "../api/scanFilters";

interface Props {
  open: boolean;
  fitsRoot: string;
  title: string;
  onCancel: () => void;
  onConfirm: (paths: string[]) => void;
}

interface TreeNode {
  entry: BrowseEntry;
  expanded: boolean;
  loaded: boolean;
  loading: boolean;
  error: string | null;
  children: TreeNode[];
}

const makeNode = (e: BrowseEntry): TreeNode => ({
  entry: e,
  expanded: false,
  loaded: false,
  loading: false,
  error: null,
  children: [],
});

const FolderBrowserModal: Component<Props> = (props) => {
  const [tree, setTree] = createStore<{ roots: TreeNode[] }>({ roots: [] });
  const [selected, setSelected] = createSignal<Set<string>>(new Set());
  const [loading, setLoading] = createSignal(false);
  const [error, setError] = createSignal<string | null>(null);

  // Resolve a path of indices to the current node inside the store.
  const nodeAt = (path: number[]): TreeNode => {
    let n: TreeNode = tree.roots[path[0]];
    for (let i = 1; i < path.length; i++) n = n.children[path[i]];
    return n;
  };

  // Mutate a node field at the given path via setTree, interleaving
  // 'children' between each index so the store can walk the tree.
  const mutateNode = <K extends keyof TreeNode>(
    path: number[],
    field: K,
    value: TreeNode[K],
  ) => {
    setTree(
      produce((s) => {
        let n: TreeNode = s.roots[path[0]];
        for (let i = 1; i < path.length; i++) n = n.children[path[i]];
        n[field] = value;
      }),
    );
  };

  const loadRoot = async () => {
    setLoading(true);
    setError(null);
    try {
      const entries = await scanFilters.browse();
      setTree("roots", entries.map(makeNode));
    } catch (e: any) {
      setError(e?.message ?? "Failed to load folders");
      setTree("roots", []);
    } finally {
      setLoading(false);
    }
  };

  const toggle = async (path: number[]) => {
    const node = nodeAt(path);
    if (node.expanded) {
      mutateNode(path, "expanded", false);
      return;
    }
    if (!node.loaded) {
      mutateNode(path, "loading", true);
      mutateNode(path, "error", null);
      try {
        const children = await scanFilters.browse(node.entry.path);
        setTree(
          produce((s) => {
            let n: TreeNode = s.roots[path[0]];
            for (let i = 1; i < path.length; i++) n = n.children[path[i]];
            n.children = children.map(makeNode);
            n.loaded = true;
            n.error = null;
            n.loading = false;
            n.expanded = true;
          }),
        );
        return;
      } catch (e: any) {
        mutateNode(path, "error", e?.message ?? "Failed to load");
        mutateNode(path, "loading", false);
        return;
      }
    }
    mutateNode(path, "expanded", true);
  };

  const retryLoad = async (path: number[]) => {
    mutateNode(path, "loaded", false);
    mutateNode(path, "error", null);
    await toggle(path);
  };

  const toggleSelected = (path: string) => {
    const s = new Set<string>(selected());
    if (s.has(path)) s.delete(path);
    else s.add(path);
    setSelected(s);
  };

  createEffect(() => {
    if (props.open) {
      setSelected(new Set<string>());
      loadRoot();
    }
  });

  const onKey = (e: KeyboardEvent) => {
    if (e.key === "Escape" && props.open) props.onCancel();
  };
  window.addEventListener("keydown", onKey);
  onCleanup(() => window.removeEventListener("keydown", onKey));

  const renderNode = (node: TreeNode, path: number[], depth: number) => (
    <div>
      <div
        class={`flex items-center gap-2 py-1 px-2 rounded ${
          node.entry.has_children ? "cursor-pointer hover:bg-theme-hover" : ""
        }`}
        style={{ "padding-left": `${depth * 16 + 8}px` }}
        onClick={() => {
          if (node.entry.has_children) toggle(path);
        }}
      >
        <Show
          when={node.entry.has_children}
          fallback={<span class="w-4 inline-block" />}
        >
          <Show
            when={!node.loading}
            fallback={
              <span
                class="w-4 inline-block text-theme-text-secondary animate-pulse select-none"
                aria-hidden="true"
              >
                ⋯
              </span>
            }
          >
            <span
              class="w-4 text-theme-text-secondary select-none"
              aria-hidden="true"
            >
              {node.expanded ? "▾" : "▸"}
            </span>
          </Show>
        </Show>
        <input
          type="checkbox"
          checked={selected().has(node.entry.path)}
          onClick={(e) => e.stopPropagation()}
          onChange={() => toggleSelected(node.entry.path)}
        />
        <span class="text-sm text-theme-text-primary truncate">{node.entry.name}</span>
      </div>
      <Show when={node.error}>
        <div
          class="flex items-center gap-2 text-xs text-theme-error"
          style={{ "padding-left": `${depth * 16 + 28}px` }}
        >
          <span>{node.error}</span>
          <button
            class="underline hover:no-underline"
            onClick={(e) => {
              e.stopPropagation();
              retryLoad(path);
            }}
          >
            Retry
          </button>
        </div>
      </Show>
      <Show when={node.expanded}>
        <For each={node.children}>
          {(child, i) => renderNode(child, [...path, i()], depth + 1)}
        </For>
      </Show>
    </div>
  );

  return (
    <Show when={props.open}>
      <div
        class="fixed inset-0 z-50 flex items-center justify-center bg-black/60"
        role="dialog"
        aria-modal="true"
        aria-labelledby="folder-browser-title"
      >
        <div class="bg-theme-surface border border-theme-border rounded-[var(--radius-md)] w-full max-w-xl max-h-[80vh] flex flex-col">
          <div class="p-4 border-b border-theme-border">
            <h3
              id="folder-browser-title"
              class="text-sm font-medium text-theme-text-primary"
            >
              {props.title}
            </h3>
            <p class="text-xs text-theme-text-secondary mt-1">
              Browse folders under <code>{props.fitsRoot}</code>
            </p>
          </div>
          <div class="flex-1 overflow-y-auto p-2">
            <Show when={loading()}>
              <div class="p-4 text-sm text-theme-text-secondary">Loading…</div>
            </Show>
            <Show when={error()}>
              <div class="p-4 text-sm text-theme-error flex items-center gap-2">
                <span>{error()}</span>
                <button
                  class="underline hover:no-underline"
                  onClick={() => loadRoot()}
                >
                  Retry
                </button>
              </div>
            </Show>
            <For each={tree.roots}>
              {(n, i) => renderNode(n, [i()], 0)}
            </For>
          </div>
          <div class="p-4 border-t border-theme-border flex items-center justify-between">
            <span class="text-xs text-theme-text-secondary">
              {selected().size} folder(s) selected
            </span>
            <div class="flex gap-2">
              <button
                class="px-4 py-1.5 bg-theme-surface text-theme-text-primary border border-theme-border rounded text-sm font-medium hover:bg-theme-hover transition-colors"
                onClick={props.onCancel}
              >
                Cancel
              </button>
              <button
                class="px-4 py-1.5 bg-theme-accent/15 text-theme-accent border border-theme-accent/30 rounded text-sm font-medium disabled:opacity-50 hover:bg-theme-accent/25 transition-colors"
                disabled={selected().size === 0}
                onClick={() => props.onConfirm(Array.from(selected()))}
              >
                Add {selected().size > 0 ? selected().size : ""}
              </button>
            </div>
          </div>
        </div>
      </div>
    </Show>
  );
};

export default FolderBrowserModal;
