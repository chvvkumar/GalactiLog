import { Component, createSignal, createEffect, onMount, onCleanup, Show } from "solid-js";
import Konva from "konva";
import { api } from "../../api/client";
import type { PanelStats } from "../../types";

// ── Constants ──────────────────────────────────────────────────────────
const SNAP = 5;
const GRID_VISUAL_SPACING = 40;
const TILE_SIZE = 300; // default tile size when thumbnail dimensions unknown
const LEGACY_CELL_PX = 320;
const GRID_LINE_COLOR = "#374151"; // gray-700
const SELECTION_COLOR = "#3b82f6"; // blue-500
const LABEL_BG = "rgba(0,0,0,0.6)";
const BADGE_BG = "rgba(59,130,246,0.8)";
const PLACEHOLDER_COLOR = "#1f2937"; // gray-800
const PLACEHOLDER_BORDER = "#4b5563"; // gray-600
const MIN_ZOOM = 0.1;
const MAX_ZOOM = 3.0;
const ZOOM_STEP = 0.1;
const FIT_PADDING = 40;
const SWAP_DURATION = 0.2; // seconds
const SAVE_DEBOUNCE_MS = 500;

// ── Props ──────────────────────────────────────────────────────────────
export interface KonvaMosaicArrangerProps {
  panels: PanelStats[];
  rotationAngle: number;
  pixelCoords: boolean;
  onSave: (
    panels: Array<{
      panel_id: string;
      grid_row: number;
      grid_col: number;
      rotation: number;
      flip_h: boolean;
    }>,
    rotationAngle: number,
  ) => void | Promise<void>;
  onPixelCoordsConverted: () => void;
}

// ── Per-tile state tracked alongside Konva nodes ──────────────────────
interface TileState {
  panelId: string;
  panelLabel: string;
  x: number;
  y: number;
  rotation: number;
  flipH: boolean;
  width: number;
  height: number;
  group: Konva.Group;
  imageNode: Konva.Image | Konva.Rect;
  labelNode: Konva.Text;
  badgeNode: Konva.Text;
  borderRect: Konva.Rect;
}

// ── Component ──────────────────────────────────────────────────────────
const KonvaMosaicArranger: Component<KonvaMosaicArrangerProps> = (props) => {
  let containerRef!: HTMLDivElement;
  let stage: Konva.Stage | null = null;
  let bgLayer: Konva.Layer | null = null;
  let tileLayer: Konva.Layer | null = null;
  let mosaicGroup: Konva.Group | null = null;

  const tiles = new Map<string, TileState>();

  const [selectedId, setSelectedId] = createSignal<string | null>(null);
  const [globalRotation, setGlobalRotation] = createSignal(props.rotationAngle ?? 0);
  const [zoom, setZoom] = createSignal(1.0);
  const [saving, setSaving] = createSignal(false);

  let saveTimer: ReturnType<typeof setTimeout> | undefined;

  // ── Debounced save ─────────────────────────────────────────────────
  const scheduleSave = () => {
    clearTimeout(saveTimer);
    saveTimer = setTimeout(async () => {
      setSaving(true);
      const panelData = Array.from(tiles.values()).map((t) => ({
        panel_id: t.panelId,
        grid_row: Math.round(t.y),
        grid_col: Math.round(t.x),
        rotation: t.rotation,
        flip_h: t.flipH,
      }));
      try {
        await props.onSave(panelData, globalRotation());
      } finally {
        setSaving(false);
      }
    }, SAVE_DEBOUNCE_MS);
  };

  // ── Badge text for rotation/flip state ─────────────────────────────
  const badgeText = (rot: number, flipH: boolean): string => {
    const parts: string[] = [];
    if (rot !== 0) parts.push(`R${rot}`);
    if (flipH) parts.push("FH");
    return parts.join(" ");
  };

  // ── Update selection highlight on a tile ───────────────────────────
  const updateSelectionVisual = (tile: TileState, selected: boolean) => {
    tile.borderRect.visible(selected);
    tileLayer?.batchDraw();
  };

  // ── Draw background grid ──────────────────────────────────────────
  const drawGrid = () => {
    if (!bgLayer || !stage) return;
    bgLayer.destroyChildren();

    const s = stage.scaleX();
    const ox = stage.x();
    const oy = stage.y();
    const w = stage.width();
    const h = stage.height();

    // Calculate visible area in stage coordinates
    const left = -ox / s;
    const top = -oy / s;
    const right = left + w / s;
    const bottom = top + h / s;

    const startX = Math.floor(left / GRID_VISUAL_SPACING) * GRID_VISUAL_SPACING;
    const endX = Math.ceil(right / GRID_VISUAL_SPACING) * GRID_VISUAL_SPACING;
    const startY = Math.floor(top / GRID_VISUAL_SPACING) * GRID_VISUAL_SPACING;
    const endY = Math.ceil(bottom / GRID_VISUAL_SPACING) * GRID_VISUAL_SPACING;

    for (let x = startX; x <= endX; x += GRID_VISUAL_SPACING) {
      bgLayer.add(
        new Konva.Line({
          points: [x, startY, x, endY],
          stroke: GRID_LINE_COLOR,
          strokeWidth: 0.5 / s,
          listening: false,
        }),
      );
    }
    for (let y = startY; y <= endY; y += GRID_VISUAL_SPACING) {
      bgLayer.add(
        new Konva.Line({
          points: [startX, y, endX, y],
          stroke: GRID_LINE_COLOR,
          strokeWidth: 0.5 / s,
          listening: false,
        }),
      );
    }
    bgLayer.batchDraw();
  };

  // ── Snap helper ────────────────────────────────────────────────────
  const snapVal = (v: number) => Math.round(v / SNAP) * SNAP;

  // ── Apply global rotation to mosaic group ──────────────────────────
  const applyGlobalRotation = () => {
    if (!mosaicGroup) return;
    // Rotate around the center of the bounding box of all tiles
    const box = getBoundingBox();
    const cx = (box.minX + box.maxX) / 2;
    const cy = (box.minY + box.maxY) / 2;
    mosaicGroup.offsetX(cx);
    mosaicGroup.offsetY(cy);
    mosaicGroup.x(cx);
    mosaicGroup.y(cy);
    mosaicGroup.rotation(globalRotation());
    tileLayer?.batchDraw();
  };

  // ── Get bounding box of all tiles ──────────────────────────────────
  const getBoundingBox = () => {
    let minX = Infinity,
      minY = Infinity,
      maxX = -Infinity,
      maxY = -Infinity;
    for (const t of tiles.values()) {
      if (t.x < minX) minX = t.x;
      if (t.y < minY) minY = t.y;
      if (t.x + t.width > maxX) maxX = t.x + t.width;
      if (t.y + t.height > maxY) maxY = t.y + t.height;
    }
    if (tiles.size === 0) return { minX: 0, minY: 0, maxX: 100, maxY: 100 };
    return { minX, minY, maxX, maxY };
  };

  // ── Fit to view ────────────────────────────────────────────────────
  const fitToView = () => {
    if (!stage) return;
    const box = getBoundingBox();
    const bw = box.maxX - box.minX;
    const bh = box.maxY - box.minY;
    if (bw <= 0 || bh <= 0) return;

    const sw = stage.width() - FIT_PADDING * 2;
    const sh = stage.height() - FIT_PADDING * 2;
    const scale = Math.min(sw / bw, sh / bh, MAX_ZOOM);
    const clampedScale = Math.max(MIN_ZOOM, Math.min(scale, MAX_ZOOM));

    const cx = (box.minX + box.maxX) / 2;
    const cy = (box.minY + box.maxY) / 2;

    stage.scaleX(clampedScale);
    stage.scaleY(clampedScale);
    stage.x(stage.width() / 2 - cx * clampedScale);
    stage.y(stage.height() / 2 - cy * clampedScale);

    setZoom(clampedScale);
    drawGrid();
    stage.batchDraw();
  };

  // ── Set zoom centered on a point ───────────────────────────────────
  const setZoomAt = (newScale: number, pointerX: number, pointerY: number) => {
    if (!stage) return;
    const clamped = Math.max(MIN_ZOOM, Math.min(newScale, MAX_ZOOM));
    const oldScale = stage.scaleX();

    const mousePointTo = {
      x: (pointerX - stage.x()) / oldScale,
      y: (pointerY - stage.y()) / oldScale,
    };

    stage.scaleX(clamped);
    stage.scaleY(clamped);
    stage.x(pointerX - mousePointTo.x * clamped);
    stage.y(pointerY - mousePointTo.y * clamped);

    setZoom(clamped);
    drawGrid();
    stage.batchDraw();
  };

  // ── Zoom buttons (center of viewport) ──────────────────────────────
  const zoomIn = () => {
    if (!stage) return;
    setZoomAt(zoom() + ZOOM_STEP, stage.width() / 2, stage.height() / 2);
  };
  const zoomOut = () => {
    if (!stage) return;
    setZoomAt(zoom() - ZOOM_STEP, stage.width() / 2, stage.height() / 2);
  };

  // ── Check bounding box overlap between two tiles ───────────────────
  const tilesOverlap = (a: TileState, b: TileState): boolean => {
    return !(
      a.x + a.width <= b.x ||
      b.x + b.width <= a.x ||
      a.y + a.height <= b.y ||
      b.y + b.height <= a.y
    );
  };

  // ── Find closest overlapping tile ──────────────────────────────────
  const findOverlapping = (movedTile: TileState): TileState | null => {
    const aCx = movedTile.x + movedTile.width / 2;
    const aCy = movedTile.y + movedTile.height / 2;
    let closest: TileState | null = null;
    let closestDist = Infinity;

    for (const t of tiles.values()) {
      if (t.panelId === movedTile.panelId) continue;
      if (!tilesOverlap(movedTile, t)) continue;
      const bCx = t.x + t.width / 2;
      const bCy = t.y + t.height / 2;
      const dist = Math.hypot(aCx - bCx, aCy - bCy);
      if (dist < closestDist) {
        closestDist = dist;
        closest = t;
      }
    }
    return closest;
  };

  // ── Swap two tiles with animation ──────────────────────────────────
  const swapTiles = (a: TileState, b: TileState) => {
    const ax = a.x,
      ay = a.y;
    const bx = b.x,
      by = b.y;

    // Update logical state
    a.x = bx;
    a.y = by;
    b.x = ax;
    b.y = ay;

    // Animate group positions
    new Konva.Tween({
      node: a.group,
      x: bx,
      y: by,
      duration: SWAP_DURATION,
      easing: Konva.Easings.EaseInOut,
      onFinish: function () { this.destroy(); },
    }).play();

    new Konva.Tween({
      node: b.group,
      x: ax,
      y: ay,
      duration: SWAP_DURATION,
      easing: Konva.Easings.EaseInOut,
      onFinish: function () { this.destroy(); },
    }).play();

    scheduleSave();
  };

  // ── Rotate selected tile CW ────────────────────────────────────────
  const rotateSelectedCW = () => {
    const id = selectedId();
    if (!id) return;
    const tile = tiles.get(id);
    if (!tile) return;
    tile.rotation = (tile.rotation + 90) % 360;
    updateTileTransform(tile);
    scheduleSave();
  };

  // ── Flip selected tile horizontal ──────────────────────────────────
  const flipSelectedH = () => {
    const id = selectedId();
    if (!id) return;
    const tile = tiles.get(id);
    if (!tile) return;
    tile.flipH = !tile.flipH;
    updateTileTransform(tile);
    scheduleSave();
  };

  // ── Update transform on image node ─────────────────────────────────
  const updateTileTransform = (tile: TileState) => {
    const img = tile.imageNode;
    // Apply rotation around tile center and horizontal flip via scaleX
    img.offsetX(tile.width / 2);
    img.offsetY(tile.height / 2);
    img.x(tile.width / 2);
    img.y(tile.height / 2);
    img.rotation(tile.rotation);
    img.scaleX(tile.flipH ? -1 : 1);

    // Update badge
    const bt = badgeText(tile.rotation, tile.flipH);
    tile.badgeNode.text(bt);
    tile.badgeNode.visible(bt.length > 0);

    tileLayer?.batchDraw();
  };

  // ── Create a Konva tile group for a panel ──────────────────────────
  const createTileGroup = (
    panel: PanelStats,
    x: number,
    y: number,
    tileW: number,
    tileH: number,
  ): TileState => {
    const group = new Konva.Group({
      x,
      y,
      draggable: true,
    });

    // Selection border (hidden by default)
    const borderRect = new Konva.Rect({
      x: -3,
      y: -3,
      width: tileW + 6,
      height: tileH + 6,
      stroke: SELECTION_COLOR,
      strokeWidth: 3,
      visible: false,
      listening: false,
    });
    group.add(borderRect);

    // Placeholder rect (used if image fails or no thumbnail)
    const placeholder = new Konva.Rect({
      width: tileW,
      height: tileH,
      fill: PLACEHOLDER_COLOR,
      stroke: PLACEHOLDER_BORDER,
      strokeWidth: 1,
      cornerRadius: 4,
    });

    // Label
    const labelNode = new Konva.Text({
      x: 4,
      y: tileH - 22,
      text: panel.panel_label,
      fontSize: 12,
      fontFamily: "sans-serif",
      fill: "white",
      padding: 3,
      listening: false,
    });
    const labelBg = new Konva.Rect({
      x: 4,
      y: tileH - 22,
      width: labelNode.width(),
      height: labelNode.height(),
      fill: LABEL_BG,
      cornerRadius: 3,
      listening: false,
    });

    // Badge (rotation/flip state)
    const bt = badgeText(panel.rotation ?? 0, panel.flip_h ?? false);
    const badgeNode = new Konva.Text({
      x: 4,
      y: 4,
      text: bt,
      fontSize: 11,
      fontFamily: "sans-serif",
      fill: "white",
      padding: 3,
      visible: bt.length > 0,
      listening: false,
    });
    const badgeBg = new Konva.Rect({
      x: 4,
      y: 4,
      width: badgeNode.width(),
      height: badgeNode.height(),
      fill: BADGE_BG,
      cornerRadius: 3,
      visible: bt.length > 0,
      listening: false,
    });

    const tile: TileState = {
      panelId: panel.panel_id,
      panelLabel: panel.panel_label,
      x,
      y,
      rotation: panel.rotation ?? 0,
      flipH: panel.flip_h ?? false,
      width: tileW,
      height: tileH,
      group,
      imageNode: placeholder, // will be replaced if thumbnail loads
      labelNode,
      badgeNode,
      borderRect,
    };

    group.add(placeholder);

    // Load thumbnail image
    if (panel.thumbnail_url) {
      const img = new Image();
      img.crossOrigin = "anonymous";
      img.onload = () => {
        if (!stage) return; // component unmounted
        // Scale to actual aspect ratio, capping the larger dimension at TILE_SIZE
        const nw = img.naturalWidth;
        const nh = img.naturalHeight;
        const scale = Math.min(TILE_SIZE / nw, TILE_SIZE / nh);
        const scaledW = Math.round(nw * scale);
        const scaledH = Math.round(nh * scale);

        // Update tile dimensions to match actual image aspect ratio
        tile.width = scaledW;
        tile.height = scaledH;

        // Resize the group and dependent nodes
        borderRect.width(scaledW + 6);
        borderRect.height(scaledH + 6);
        labelNode.y(scaledH - 22);
        labelBg.y(scaledH - 22);

        const konvaImg = new Konva.Image({
          image: img,
          width: scaledW,
          height: scaledH,
          cornerRadius: 4,
        });
        // Replace placeholder with loaded image
        placeholder.destroy();
        group.add(konvaImg);
        // Move label/badge to top
        badgeBg.moveToTop();
        badgeNode.moveToTop();
        labelBg.moveToTop();
        labelNode.moveToTop();
        borderRect.moveToTop();

        tile.imageNode = konvaImg;
        updateTileTransform(tile);
        tileLayer?.batchDraw();
      };
      img.onerror = () => {
        if (!stage) return; // component unmounted
        // Keep placeholder
        updateTileTransform(tile);
      };
      img.src = api.thumbnailUrl(panel.thumbnail_url);
    }

    group.add(badgeBg, badgeNode, labelBg, labelNode);
    borderRect.moveToTop();

    // Apply initial transform
    updateTileTransform(tile);

    // ── Drag events ────────────────────────────────────────────────
    group.on("dragstart", () => {
      stage?.draggable(false);
      group.moveToTop();
      mosaicGroup?.getLayer()?.batchDraw();
    });

    group.on("dragmove", () => {
      group.x(snapVal(group.x()));
      group.y(snapVal(group.y()));
    });

    group.on("dragend", () => {
      stage?.draggable(true);
      tile.x = group.x();
      tile.y = group.y();
      scheduleSave();
    });

    // ── Right-click to select + rotate CW ────────────────────────
    group.on("contextmenu", (e) => {
      e.evt.preventDefault();
      e.cancelBubble = true;
      const prev = selectedId();
      if (prev && prev !== tile.panelId) {
        const prevTile = tiles.get(prev);
        if (prevTile) updateSelectionVisual(prevTile, false);
      }
      setSelectedId(tile.panelId);
      updateSelectionVisual(tile, true);
      tile.rotation = (tile.rotation + 90) % 360;
      updateTileTransform(tile);
      scheduleSave();
    });

    // ── Click to select ────────────────────────────────────────────
    group.on("click tap", (e) => {
      e.cancelBubble = true;
      const prev = selectedId();
      if (prev && prev !== tile.panelId) {
        const prevTile = tiles.get(prev);
        if (prevTile) updateSelectionVisual(prevTile, false);
      }
      setSelectedId(tile.panelId);
      updateSelectionVisual(tile, true);
      group.moveToTop();
      mosaicGroup?.getLayer()?.batchDraw();
    });

    return tile;
  };

  // ── Initialize stage and build tiles ───────────────────────────────
  onMount(() => {
    const containerWidth = containerRef.clientWidth || 800;
    const containerHeight = 600;

    stage = new Konva.Stage({
      container: containerRef,
      width: containerWidth,
      height: containerHeight,
    });

    bgLayer = new Konva.Layer({ listening: false });
    tileLayer = new Konva.Layer();
    mosaicGroup = new Konva.Group();
    tileLayer.add(mosaicGroup);

    stage.add(bgLayer);
    stage.add(tileLayer);

    // ── Click on empty space to deselect ───────────────────────────
    stage.on("click tap", (e) => {
      if (e.target === stage) {
        const prev = selectedId();
        if (prev) {
          const prevTile = tiles.get(prev);
          if (prevTile) updateSelectionVisual(prevTile, false);
        }
        setSelectedId(null);
      }
    });

    // ── Mouse wheel zoom ───────────────────────────────────────────
    stage.on("wheel", (e) => {
      e.evt.preventDefault();
      const pointer = stage!.getPointerPosition();
      if (!pointer) return;
      const direction = e.evt.deltaY > 0 ? -1 : 1;
      const newScale = zoom() + direction * ZOOM_STEP;
      setZoomAt(newScale, pointer.x, pointer.y);
    });

    // ── Pan via drag on empty space ────────────────────────────────
    // Only the stage itself should be draggable for panning.
    // Tile groups handle their own dragging independently.
    stage.draggable(true);
    stage.on("dragmove", (e) => {
      if (e.target === stage) {
        drawGrid();
      }
    });

    // Build tiles from props
    buildTiles(props.panels);
    drawGrid();

    // Handle resize
    const resizeObserver = new ResizeObserver(() => {
      if (!stage || !containerRef) return;
      stage.width(containerRef.clientWidth);
      stage.height(containerRef.clientHeight);
      drawGrid();
    });
    resizeObserver.observe(containerRef);

    onCleanup(() => {
      resizeObserver.disconnect();
      clearTimeout(saveTimer);
      stage?.destroy();
      stage = null;
    });
  });

  // ── Build/rebuild tiles from panel data ────────────────────────────
  const buildTiles = (panels: PanelStats[]) => {
    if (!mosaicGroup) return;

    // Clear existing
    for (const t of tiles.values()) {
      t.group.destroy();
    }
    tiles.clear();

    const isLegacy = !props.pixelCoords;

    // Count panels with null coordinates so we can auto-arrange them in a grid
    const nullCount = panels.filter(
      (p) => p.grid_col == null || p.grid_row == null,
    ).length;
    const nullCols = nullCount > 0 ? Math.ceil(Math.sqrt(nullCount)) : 1;
    let nullIdx = 0;

    for (const panel of panels) {
      let px: number;
      let py: number;

      if (panel.grid_col == null || panel.grid_row == null) {
        // Auto-arrange null-coordinate panels in a roughly square grid
        px = (nullIdx % nullCols) * (TILE_SIZE + SNAP);
        py = Math.floor(nullIdx / nullCols) * (TILE_SIZE + SNAP);
        nullIdx++;
      } else {
        px = panel.grid_col;
        py = panel.grid_row;

        if (isLegacy) {
          // Convert small integer grid positions to pixel coordinates
          px *= LEGACY_CELL_PX;
          py *= LEGACY_CELL_PX;
        }
      }

      const tileW = TILE_SIZE;
      const tileH = TILE_SIZE;

      const tile = createTileGroup(panel, px, py, tileW, tileH);
      tiles.set(panel.panel_id, tile);
      mosaicGroup.add(tile.group);
    }

    applyGlobalRotation();
    tileLayer?.batchDraw();

    // If legacy, immediately save converted coordinates and notify
    if (isLegacy && panels.length > 0) {
      const panelData = Array.from(tiles.values()).map((t) => ({
        panel_id: t.panelId,
        grid_row: Math.round(t.y),
        grid_col: Math.round(t.x),
        rotation: t.rotation,
        flip_h: t.flipH,
      }));
      (async () => {
        try {
          await props.onSave(panelData, globalRotation());
          props.onPixelCoordsConverted();
        } catch (e) {
          console.error("Legacy conversion save failed:", e);
        }
      })();
    }

    // Fit after initial build
    setTimeout(() => fitToView(), 50);
  };

  // ── React to panel prop changes ────────────────────────────────────
  createEffect(() => {
    const panels = props.panels;
    // Only rebuild if panel set changed (check by panel_id set)
    if (tiles.size > 0) {
      const currentIds = new Set(tiles.keys());
      const newIds = new Set(panels.map((p) => p.panel_id));
      const same =
        currentIds.size === newIds.size &&
        [...currentIds].every((id) => newIds.has(id));
      if (same) return; // No structural change, skip rebuild
    }
    if (mosaicGroup && panels.length > 0) {
      buildTiles(panels);
    }
  });

  // ── Sync global rotation signal to Konva group ─────────────────────
  let rotationInitialized = false;
  createEffect(() => {
    // Track the signal so the effect re-runs on rotation changes
    void globalRotation();
    applyGlobalRotation();
    // Skip save on initial mount; only save after user interaction
    if (rotationInitialized) {
      scheduleSave();
    }
    rotationInitialized = true;
  });

  // ── Reset global rotation ──────────────────────────────────────────
  const resetRotation = () => {
    setGlobalRotation(0);
  };

  return (
    <div class="space-y-3">
      {/* Toolbar */}
      <div class="flex flex-wrap items-center gap-2 bg-theme-elevated rounded px-3 py-2 text-sm text-theme-text">
        {/* Tile operations */}
        <button
          class="px-2 py-1 rounded bg-theme-surface hover:bg-theme-hover disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
          disabled={!selectedId()}
          onClick={rotateSelectedCW}
          title="Rotate selected tile 90 CW"
        >
          Rotate CW
        </button>
        <button
          class="px-2 py-1 rounded bg-theme-surface hover:bg-theme-hover disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
          disabled={!selectedId()}
          onClick={flipSelectedH}
          title="Flip selected tile horizontally"
        >
          Flip H
        </button>

        <div class="w-px h-5 bg-theme-border" />

        {/* View controls */}
        <button
          class="px-2 py-1 rounded bg-theme-surface hover:bg-theme-hover transition-colors"
          onClick={fitToView}
          title="Fit all tiles to viewport"
        >
          Fit
        </button>
        <button
          class="px-2 py-1 rounded bg-theme-surface hover:bg-theme-hover transition-colors"
          onClick={zoomOut}
          title="Zoom out"
        >
          -
        </button>
        <span class="text-xs tabular-nums w-12 text-center">
          {Math.round(zoom() * 100)}%
        </span>
        <button
          class="px-2 py-1 rounded bg-theme-surface hover:bg-theme-hover transition-colors"
          onClick={zoomIn}
          title="Zoom in"
        >
          +
        </button>

        <div class="w-px h-5 bg-theme-border" />

        {/* Global rotation */}
        <label class="flex items-center gap-2 text-xs">
          <span class="text-theme-text-secondary">Rotation</span>
          <input
            type="range"
            min={-180}
            max={180}
            step={1}
            value={globalRotation()}
            onInput={(e) => setGlobalRotation(parseInt(e.currentTarget.value, 10))}
            class="w-28 accent-blue-500"
          />
          <span class="tabular-nums w-10 text-center">{globalRotation()}&deg;</span>
        </label>
        <button
          class="px-2 py-1 rounded bg-theme-surface hover:bg-theme-hover transition-colors text-xs"
          onClick={resetRotation}
          title="Reset rotation to 0"
        >
          Reset
        </button>

        <Show when={saving()}>
          <span class="ml-auto text-xs text-theme-text-secondary">Saving...</span>
        </Show>
      </div>

      {/* Canvas container */}
      <div
        ref={containerRef!}
        class="w-full rounded border border-theme-border bg-theme-surface"
        style={{ height: "600px", cursor: "grab" }}
      />
    </div>
  );
};

export default KonvaMosaicArranger;
