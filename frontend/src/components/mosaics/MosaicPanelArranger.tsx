import { Component, For, Show, createMemo, createSignal, createEffect, onCleanup } from "solid-js";
import { createStore, produce } from "solid-js/store";
import {
  DragDropProvider,
  DragDropSensors,
  createDraggable,
  createDroppable,
  type CollisionDetector,
  type Draggable,
  type Droppable,
} from "@thisbeyond/solid-dnd";
import { api } from "../../api/client";
import type { PanelStats } from "../../types";
import { formatIntegration } from "../../utils/format";
import { FilePreviewModal } from "../FilePreviewModal";

interface Props {
  mosaicId: string;
  panels: PanelStats[];
  onChange?: () => void;
}

type LocalPanel = PanelStats & { _row: number; _col: number };

const CELL_MAX_PX = 360;
const GAP_PX = 6;

function buildInitialLayout(panels: PanelStats[]): { cells: LocalPanel[]; rows: number; cols: number } {
  const n = panels.length;
  if (n === 0) return { cells: [], rows: 0, cols: 0 };

  const placed = panels.filter((p) => p.grid_row != null && p.grid_col != null);
  const unplaced = panels.filter((p) => p.grid_row == null || p.grid_col == null);

  const autoCols = Math.max(1, Math.ceil(Math.sqrt(n)));
  let rows = 0;
  let cols = autoCols;

  // Start with placed panels at their stored position.
  const used = new Set<string>();
  const cells: LocalPanel[] = placed.map((p) => {
    const r = p.grid_row as number;
    const c = p.grid_col as number;
    used.add(`${r},${c}`);
    rows = Math.max(rows, r + 1);
    cols = Math.max(cols, c + 1);
    return { ...p, _row: r, _col: c };
  });

  // Fill unplaced panels into the next free cells in row-major order.
  // Expand rows as needed; keep cols stable.
  if (unplaced.length > 0) {
    const sorted = [...unplaced].sort((a, b) => a.sort_order - b.sort_order);
    let r = 0;
    let c = 0;
    for (const p of sorted) {
      while (used.has(`${r},${c}`)) {
        c += 1;
        if (c >= cols) {
          c = 0;
          r += 1;
        }
      }
      used.add(`${r},${c}`);
      cells.push({ ...p, _row: r, _col: c });
      rows = Math.max(rows, r + 1);
    }
  }

  return { cells, rows: Math.max(1, rows), cols: Math.max(1, cols) };
}

const MosaicPanelArranger: Component<Props> = (props) => {
  // Store gives us fine-grained reactivity: mutating panel._row in place keeps
  // the panel's object identity stable, so <For> (keyed by reference) does not
  // destroy and recreate PanelDraggable, which would leave solid-dnd with
  // stale draggable registrations.
  const [cells, setCells] = createStore<LocalPanel[]>([]);
  const [activeId, setActiveId] = createSignal<string | null>(null);
  const [saving, setSaving] = createSignal(false);
  const [initialized, setInitialized] = createSignal(false);
  const [pointerPos, setPointerPos] = createSignal<{ x: number; y: number } | null>(null);

  // Track the real pointer position while a drag is active. The built-in
  // collision detectors (mostIntersecting, closestCenter) use the draggable's
  // translated bbox, which depends on where inside the tile the user grabbed
  // -- grabbing near the bottom makes the tile sit above the pointer and the
  // highlighted cell is one row off. A pointer-driven detector eliminates
  // that asymmetry.
  createEffect(() => {
    if (activeId() === null) {
      setPointerPos(null);
      return;
    }
    const handler = (e: PointerEvent) => setPointerPos({ x: e.clientX, y: e.clientY });
    window.addEventListener("pointermove", handler);
    onCleanup(() => window.removeEventListener("pointermove", handler));
  });

  const pointerCollisionDetector: CollisionDetector = (_draggable, droppables) => {
    const pos = pointerPos();
    if (!pos) return null;
    // Prefer a droppable whose bbox strictly contains the pointer.
    for (const d of droppables) {
      const l = d.layout;
      if (pos.x >= l.left && pos.x <= l.right && pos.y >= l.top && pos.y <= l.bottom) {
        return d;
      }
    }
    // Fallback: closest droppable center to pointer (forgiving when the
    // pointer slips into a gap between cells).
    let best: Droppable | null = null;
    let bestDist = Infinity;
    for (const d of droppables) {
      const c = d.layout.center;
      const dx = c.x - pos.x;
      const dy = c.y - pos.y;
      const dist = dx * dx + dy * dy;
      if (dist < bestDist) {
        bestDist = dist;
        best = d;
      }
    }
    return best;
  };

  // Seed local state from props once. Subsequent updates are driven by user
  // interaction -- we do NOT re-derive from props.panels because the backend
  // echoes the same state we just pushed, which would race with optimistic
  // updates and wipe in-flight edits.
  createEffect(() => {
    if (initialized()) return;
    if (props.panels.length === 0) return;
    const { cells: c } = buildInitialLayout(props.panels);
    setCells(c);
    setInitialized(true);
  });

  const maxIntegration = createMemo(() =>
    Math.max(1, ...props.panels.map((p) => p.total_integration_seconds)),
  );

  const cellAt = (row: number, col: number) =>
    cells.find((c) => c._row === row && c._col === col);

  // Tight bounding box over placed panels, then expanded by one cell in every
  // direction to give the user drop targets for extending the grid.
  const bbox = createMemo(() => {
    if (cells.length === 0) return { minR: 0, maxR: 0, minC: 0, maxC: 0 };
    let minR = Infinity, maxR = -Infinity, minC = Infinity, maxC = -Infinity;
    for (const p of cells) {
      if (p._row < minR) minR = p._row;
      if (p._row > maxR) maxR = p._row;
      if (p._col < minC) minC = p._col;
      if (p._col > maxC) maxC = p._col;
    }
    return { minR, maxR, minC, maxC };
  });
  const extBox = createMemo(() => {
    const b = bbox();
    return { minR: b.minR - 1, maxR: b.maxR + 1, minC: b.minC - 1, maxC: b.maxC + 1 };
  });
  // Tight bbox at rest; extended (with 1-cell drop margin) during an active drag.
  const displayBox = createMemo(() =>
    activeId() !== null ? extBox() : bbox(),
  );
  const renderRows = createMemo(() => displayBox().maxR - displayBox().minR + 1);
  const renderCols = createMemo(() => displayBox().maxC - displayBox().minC + 1);

  const persist = async (panelId: string, patch: Partial<PanelStats>) => {
    setSaving(true);
    try {
      await api.updateMosaicPanel(props.mosaicId, panelId, {
        grid_row: patch.grid_row ?? undefined,
        grid_col: patch.grid_col ?? undefined,
        rotation: patch.rotation ?? undefined,
        flip_h: patch.flip_h ?? undefined,
      });
    } finally {
      setSaving(false);
    }
  };

  const handleDragEnd = (event: { draggable: Draggable; droppable?: Droppable | null }) => {
    const { draggable, droppable } = event;
    setActiveId(null);
    if (!droppable) return;
    const panelId = String(draggable.id);
    const target = String(droppable.id);
    const match = target.match(/^cell-(-?\d+)-(-?\d+)$/);
    if (!match) return;
    const tRow = parseInt(match[1], 10);
    const tCol = parseInt(match[2], 10);

    const src = cells.find((c) => c.panel_id === panelId);
    if (!src) return;
    if (src._row === tRow && src._col === tCol) return;

    const dst = cellAt(tRow, tCol);
    const srcRow = src._row;
    const srcCol = src._col;

    // Mutate in place via produce so panel object identity is preserved.
    setCells(
      produce((draft) => {
        for (const c of draft) {
          if (c.panel_id === panelId) {
            c._row = tRow;
            c._col = tCol;
            c.grid_row = tRow;
            c.grid_col = tCol;
          } else if (dst && c.panel_id === dst.panel_id) {
            c._row = srcRow;
            c._col = srcCol;
            c.grid_row = srcRow;
            c.grid_col = srcCol;
          }
        }
      }),
    );

    persist(panelId, { grid_row: tRow, grid_col: tCol });
    if (dst) {
      persist(dst.panel_id, { grid_row: srcRow, grid_col: srcCol });
    }
  };

  const rotatePanel = (panelId: string) => {
    let rot = 0;
    setCells(
      produce((draft) => {
        const c = draft.find((c) => c.panel_id === panelId);
        if (c) {
          c.rotation = ((c.rotation ?? 0) + 90) % 360;
          rot = c.rotation;
        }
      }),
    );
    persist(panelId, { rotation: rot });
  };

  const flipPanel = (panelId: string) => {
    let flip = false;
    setCells(
      produce((draft) => {
        const c = draft.find((c) => c.panel_id === panelId);
        if (c) {
          c.flip_h = !c.flip_h;
          flip = c.flip_h;
        }
      }),
    );
    persist(panelId, { flip_h: flip });
  };

  const meridianFlip = (panelId: string) => {
    let rot = 0;
    setCells(
      produce((draft) => {
        const c = draft.find((c) => c.panel_id === panelId);
        if (c) {
          c.rotation = ((c.rotation ?? 0) + 180) % 360;
          rot = c.rotation;
        }
      }),
    );
    persist(panelId, { rotation: rot });
  };

  return (
    <div class="space-y-3">
      <div class="flex items-center gap-2 text-xs text-theme-text-secondary">
        <span>Drag to rearrange. Drop into an edge cell to extend the grid in any direction.</span>
        <Show when={saving()}>
          <span class="ml-auto text-theme-text-secondary">Saving...</span>
        </Show>
      </div>

      <DragDropProvider
        onDragStart={({ draggable }: { draggable: Draggable }) => setActiveId(String(draggable.id))}
        onDragEnd={handleDragEnd}
        collisionDetector={pointerCollisionDetector}
      >
        <DragDropSensors />
        <div
          class="mx-auto w-full"
          style={{
            display: "grid",
            "grid-template-columns": `repeat(${renderCols()}, minmax(0, 1fr))`,
            "grid-auto-rows": "auto",
            gap: `${GAP_PX}px`,
            "max-width": `${renderCols() * CELL_MAX_PX + (renderCols() - 1) * GAP_PX}px`,
          }}
        >
          {/* Droppable background cells over the display bounding box. */}
          <For each={Array.from({ length: renderRows() * renderCols() }, (_, i) => i)}>
            {(i) => {
              const r = Math.floor(i / renderCols()) + displayBox().minR;
              const c = (i % renderCols()) + displayBox().minC;
              const panel = cellAt(r, c);
              return (
                <DropCell
                  row={r}
                  col={c}
                  cssRow={r - displayBox().minR + 1}
                  cssCol={c - displayBox().minC + 1}
                  hasPanel={!!panel}
                  isSource={!!panel && panel.panel_id === activeId()}
                  isDragging={activeId() !== null}
                />
              );
            }}
          </For>

          {/* Draggable panels -- keyed by panel_id, positioned via grid-area */}
          <For each={cells}>
            {(panel) => (
              <PanelDraggable
                panel={panel}
                extMinR={displayBox().minR}
                extMinC={displayBox().minC}
                maxIntegration={maxIntegration()}
                isActive={activeId() === panel.panel_id}
                onRotate={rotatePanel}
                onFlip={flipPanel}
                onMeridianFlip={meridianFlip}
              />
            )}
          </For>
        </div>
      </DragDropProvider>
    </div>
  );
};

const DropCell: Component<{
  row: number;
  col: number;
  cssRow: number;
  cssCol: number;
  hasPanel: boolean;
  isSource: boolean;
  isDragging: boolean;
}> = (props) => {
  const droppable = createDroppable(`cell-${props.row}-${props.col}`);
  const isHovered = () => droppable.isActiveDroppable;

  return (
    <div
      ref={droppable.ref}
      class="relative rounded transition-all duration-150"
      classList={{
        "ring-4 ring-theme-accent bg-theme-accent/15": isHovered() && !props.isSource,
        "ring-2 ring-theme-accent/50 border-dashed bg-theme-accent/5": props.isSource,
        "ring-2 ring-theme-border border-dashed": props.isDragging && !isHovered() && !props.isSource,
      }}
      style={{
        "grid-row": `${props.cssRow}`,
        "grid-column": `${props.cssCol}`,
        "aspect-ratio": "1 / 1",
      }}
    >
      <Show when={props.isDragging && (!props.hasPanel || props.isSource)}>
        <div
          class="w-full h-full flex items-center justify-center text-caption transition-colors"
          classList={{
            "text-theme-accent": isHovered(),
            "text-theme-text-secondary/60": !isHovered(),
          }}
        >
          {isHovered() ? "drop here" : props.isSource ? "" : "empty"}
        </div>
      </Show>
    </div>
  );
};

const PanelDraggable: Component<{
  panel: LocalPanel;
  extMinR: number;
  extMinC: number;
  maxIntegration: number;
  isActive: boolean;
  onRotate: (id: string) => void;
  onFlip: (id: string) => void;
  onMeridianFlip: (id: string) => void;
}> = (props) => {
  const draggable = createDraggable(props.panel.panel_id);

  return (
    <div
      ref={draggable.ref}
      class="rounded transition-[box-shadow,transform] duration-150"
      classList={{
        "ring-4 ring-theme-accent shadow-2xl scale-105": props.isActive,
      }}
      style={{
        "grid-row": `${props.panel._row - props.extMinR + 1}`,
        "grid-column": `${props.panel._col - props.extMinC + 1}`,
        "aspect-ratio": "1 / 1",
        "z-index": props.isActive ? 1000 : 2,
        "pointer-events": "auto",
      }}
    >
      <div class="relative group w-full h-full">
        <div
          class={`absolute inset-0 ${props.isActive ? "cursor-grabbing" : "cursor-grab"}`}
          {...draggable.dragActivators}
        >
          <PanelThumbnail panel={props.panel} maxIntegration={props.maxIntegration} />
        </div>
        <div class="absolute top-1 right-1 flex flex-col gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
          <IconButton
            title="Rotate 90° CW"
            onClick={() => props.onRotate(props.panel.panel_id)}
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <polyline points="23 4 23 10 17 10" />
              <path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10" />
            </svg>
          </IconButton>
          <IconButton
            title="Flip horizontal"
            onClick={() => props.onFlip(props.panel.panel_id)}
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M12 3v18" />
              <path d="M16 7l4 5-4 5" />
              <path d="M8 7l-4 5 4 5" />
            </svg>
          </IconButton>
          <IconButton
            title="Meridian flip (rotate 180°)"
            onClick={() => props.onMeridianFlip(props.panel.panel_id)}
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M12 2v20" />
              <path d="M4 12h16" />
              <circle cx="12" cy="12" r="9" />
            </svg>
          </IconButton>
        </div>
      </div>
    </div>
  );
};

const PanelThumbnail: Component<{ panel: LocalPanel; maxIntegration: number }> = (props) => {
  const [previewOpen, setPreviewOpen] = createSignal(false);
  // Distinguish click from drag: drag activators on the parent div need
  // pointerdown to bubble through, so we can't stopPropagation here.
  // Track pointer movement and only open the preview on release if the
  // pointer stayed near the press point (i.e. the user didn't drag).
  let downX = 0;
  let downY = 0;
  let moved = false;
  const DRAG_THRESHOLD_PX = 5;

  const transform = () => {
    const rot = props.panel.rotation ?? 0;
    const flip = props.panel.flip_h ? " scaleX(-1)" : "";
    return `rotate(${rot}deg)${flip}`;
  };

  const diff = () => props.panel.total_integration_seconds - props.maxIntegration;

  return (
    <div class="relative w-full h-full">
      <Show
        when={props.panel.thumbnail_url}
        fallback={
          <div class="w-full h-full bg-theme-elevated border border-theme-border rounded flex items-center justify-center text-theme-text-secondary text-xs">
            {props.panel.panel_label}
          </div>
        }
      >
        <button
          type="button"
          class="w-full h-full p-0 border-0 bg-transparent cursor-pointer"
          onPointerDown={(e) => {
            downX = e.clientX;
            downY = e.clientY;
            moved = false;
          }}
          onPointerMove={(e) => {
            if (!moved && Math.hypot(e.clientX - downX, e.clientY - downY) > DRAG_THRESHOLD_PX) {
              moved = true;
            }
          }}
          onClick={(e) => {
            if (moved) {
              e.preventDefault();
              return;
            }
            if (props.panel.thumbnail_image_id) setPreviewOpen(true);
          }}
        >
          <img
            src={api.thumbnailUrl(props.panel.thumbnail_url!)}
            alt={props.panel.panel_label}
            class="w-full h-full object-cover rounded border border-theme-border"
            style={{ transform: transform(), "transition": "transform 160ms ease" }}
            draggable={false}
            loading="lazy"
            width={360}
            height={360}
          />
        </button>
      </Show>
      <span class="absolute bottom-1 left-1 bg-black/60 text-white text-caption px-1.5 py-0.5 rounded pointer-events-none">
        {props.panel.panel_label}
      </span>
      <span class="absolute bottom-1 right-1 bg-black/60 text-white text-caption px-1.5 py-0.5 rounded pointer-events-none">
        {formatIntegration(props.panel.total_integration_seconds)}
        <Show when={diff() < 0}>
          <span class="ml-1 text-amber-300">-{formatIntegration(Math.abs(diff()))}</span>
        </Show>
      </span>
      <Show when={props.panel.flip_h || (props.panel.rotation ?? 0) !== 0}>
        <span class="absolute top-1 left-1 bg-theme-accent/80 text-white text-caption px-1.5 py-0.5 rounded pointer-events-none">
          {props.panel.rotation ?? 0}°{props.panel.flip_h ? " ⇋" : ""}
        </span>
      </Show>
      <Show when={previewOpen() && props.panel.thumbnail_image_id}>
        <FilePreviewModal
          imageId={props.panel.thumbnail_image_id!}
          filePath={props.panel.thumbnail_file_path ?? ""}
          thumbnailUrl={props.panel.thumbnail_url ? api.thumbnailUrl(props.panel.thumbnail_url) : null}
          onClose={() => setPreviewOpen(false)}
        />
      </Show>
    </div>
  );
};

const IconButton: Component<{ title: string; onClick: () => void; children: any }> = (props) => (
  <button
    class="w-6 h-6 flex items-center justify-center rounded bg-black/60 text-white hover:bg-black/80 transition-colors"
    title={props.title}
    onClick={(e) => { e.stopPropagation(); props.onClick(); }}
    onPointerDown={(e) => e.stopPropagation()}
  >
    {props.children}
  </button>
);

export default MosaicPanelArranger;
