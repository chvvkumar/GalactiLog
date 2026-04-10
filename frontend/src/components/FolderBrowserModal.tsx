import { Component, createSignal, createEffect, Show, For } from "solid-js";
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
  children: TreeNode[];
}

const FolderBrowserModal: Component<Props> = (props) => {
  const [nodes, setNodes] = createSignal<TreeNode[]>([]);
  const [selected, setSelected] = createSignal<Set<string>>(new Set());
  const [loading, setLoading] = createSignal(false);
  const [error, setError] = createSignal<string | null>(null);

  const loadRoot = async () => {
    setLoading(true);
    setError(null);
    try {
      const entries = await scanFilters.browse();
      setNodes(entries.map((e) => ({
        entry: e, expanded: false, loaded: false, children: [],
      })));
    } catch (e: any) {
      setError(e?.message ?? "Failed to load folders");
    } finally {
      setLoading(false);
    }
  };

  const toggle = async (node: TreeNode) => {
    if (node.expanded) {
      node.expanded = false;
      setNodes([...nodes()]);
      return;
    }
    if (!node.loaded) {
      try {
        const children = await scanFilters.browse(node.entry.path);
        node.children = children.map((e) => ({
          entry: e, expanded: false, loaded: false, children: [],
        }));
        node.loaded = true;
      } catch (e: any) {
        setError(e?.message ?? "Failed to load");
        return;
      }
    }
    node.expanded = true;
    setNodes([...nodes()]);
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

  const renderNode = (node: TreeNode, depth: number) => (
    <div>
      <div
        class={`flex items-center gap-2 py-1 px-2 rounded ${
          node.entry.has_children ? "cursor-pointer hover:bg-theme-hover" : ""
        }`}
        style={{ "padding-left": `${depth * 16 + 8}px` }}
        onClick={() => {
          if (node.entry.has_children) toggle(node);
        }}
      >
        <Show
          when={node.entry.has_children}
          fallback={<span class="w-4 inline-block" />}
        >
          <span
            class="w-4 text-theme-text-secondary select-none"
            aria-hidden="true"
          >
            {node.expanded ? "▾" : "▸"}
          </span>
        </Show>
        <input
          type="checkbox"
          checked={selected().has(node.entry.path)}
          onClick={(e) => e.stopPropagation()}
          onChange={() => toggleSelected(node.entry.path)}
        />
        <span class="text-sm text-theme-text-primary truncate">{node.entry.name}</span>
      </div>
      <Show when={node.expanded}>
        <For each={node.children}>
          {(child) => renderNode(child, depth + 1)}
        </For>
      </Show>
    </div>
  );

  return (
    <Show when={props.open}>
      <div class="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
        <div class="bg-theme-surface border border-theme-border rounded-[var(--radius-md)] w-full max-w-xl max-h-[80vh] flex flex-col">
          <div class="p-4 border-b border-theme-border">
            <h3 class="text-sm font-medium text-theme-text-primary">{props.title}</h3>
            <p class="text-xs text-theme-text-secondary mt-1">
              Browse folders under <code>{props.fitsRoot}</code>
            </p>
          </div>
          <div class="flex-1 overflow-y-auto p-2">
            <Show when={loading()}>
              <div class="p-4 text-sm">Loading…</div>
            </Show>
            <Show when={error()}>
              <div class="p-4 text-sm text-red-400">{error()}</div>
            </Show>
            <For each={nodes()}>{(n) => renderNode(n, 0)}</For>
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
