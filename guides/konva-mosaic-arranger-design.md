# Konva.js Mosaic Panel Arranger

## Problem Statement

The current mosaic panel arranger uses @thisbeyond/solid-dnd v0.7.5 (unmaintained since mid-2023) with CSS Grid for tile arrangement. Three issues make it unusable for real mosaic layouts:

1. Tile positions do not update in real-time during drag. The optimistic update system intentionally avoids re-deriving from props (to prevent race conditions), causing stale visual state until page reload.
2. Gaps appear between panels after rearrangement. The bounding box toggles between a tight fit (at rest) and an extended box (+1 cell in all directions during drag), causing CSS Grid to reflow unpredictably.
3. The canvas resizes in unexpected ways when dropping tiles into edge cells. The extended-to-tight bounding box transition on drop causes the grid dimensions to jump.

Additionally, the current implementation forces all tiles into uniform square cells (1:1 aspect ratio, max 360px). Real mosaic panels have varying aspect ratios, and mosaic layouts can be diagonal/staircase patterns that do not fit a rectangular grid axis.

## Decision

Replace MosaicPanelArranger.tsx with a Konva.js canvas-based component (KonvaMosaicArranger.tsx). Konva.js provides:

- Free-form pixel positioning (no grid-cell constraints)
- Native node rotation and scale transforms
- Group rotation for the entire mosaic arrangement
- Real-time drag feedback via dragmove events
- Two-layer architecture separating static background from interactive tiles
- Built-in Stage zoom/pan via scale and position
- Coordinate transform handling inside rotated groups (drag works correctly even when the mosaic group is rotated)

Alternatives evaluated:
- GridStack.js: Cannot handle variable aspect ratio tiles or diagonal layouts. Column-based grid forces axis-aligned positioning.
- Vanilla DnD (pointer events + CSS Grid): Same axis-alignment limitation as the current approach. No zoom/pan.
- @thisbeyond/solid-dnd improvements: Library is unmaintained. The fundamental CSS Grid constraint remains.

## Architecture

### Component hierarchy

```
MosaicDetailPage
  KonvaMosaicArranger (new, replaces MosaicPanelArranger)
    Konva.Stage
      Background Layer (grid lines, non-interactive)
      Tile Layer
        Mosaic Group (global rotation applied here)
          TileGroup per panel:
            Konva.Image (thumbnail)
            Konva.Text (panel label)
            Konva.Rect (selection highlight border)
            Konva.Text (rotation/flip state badge)
  MosaicGrid (read-only SVG spatial view, unchanged)
  Session table (unchanged)
```

### SolidJS integration pattern

Konva has no maintained SolidJS wrapper. Integration is imperative:

- `onMount`: create Stage, Layers, load images, build tile groups
- `createEffect`: bridge SolidJS signals (panel data, selection state) to Konva node properties
- `onCleanup`: destroy the Stage to prevent memory leaks
- SolidJS signals for: selected tile ID, global rotation angle, zoom level, panel positions (for the JSON debug view and save triggers)

### Data flow

1. Page fetches mosaic + panels from API
2. KonvaMosaicArranger receives panels as props, initializes Konva nodes on mount
3. User drags tile: dragmove snaps to 20px grid, dragend updates local SolidJS signal (optimistic)
4. Save is debounced (500ms after last change): batch PUT sends all panel positions + global rotation
5. Rotate/flip per tile: updates Konva node, triggers same debounced save
6. Global rotation: slider updates Konva Group rotation, triggers save of mosaic rotation_angle

### Migration of existing positions

Existing mosaics store grid_row/grid_col as small integers (0, 1, 2, etc.) representing cell indices. With Konva, these become pixel coordinates. A new boolean column `pixel_coords` on the `mosaics` table (default false) distinguishes legacy from converted mosaics.

Migration strategy:
- When `pixel_coords` is false, grid_row/grid_col are legacy cell indices.
- When `pixel_coords` is true, grid_row/grid_col are pixel coordinates.
- On first load of a mosaic where `pixel_coords` is false, the frontend multiplies each panel's grid_row/grid_col by a default cell spacing of 320px (chosen as a middle ground for typical panel sizes). It then saves the converted pixel positions and sets `pixel_coords=true` via the mosaic update endpoint.
- This is a one-way migration. Once converted, the mosaic stays in pixel coordinate mode.
- The `pixel_coords` column is added in the same Alembic migration as `rotation_angle`.

## Backend Changes

### New columns

**mosaics.rotation_angle**
- Type: Float, default 0.0, nullable
- Purpose: stores the global mosaic rotation angle in degrees (-180 to +180)

**mosaics.pixel_coords**
- Type: Boolean, default false, non-nullable
- Purpose: distinguishes legacy cell-index positions (false) from pixel coordinate positions (true). See "Migration of existing positions" above.

Both columns are added in a single Alembic migration with defensive _add_column_if_not_exists helper (per project convention, see migration 0013 pattern).

### New endpoint: PUT /{mosaic_id}/panels/batch

Request body:
```json
[
  {
    "panel_id": "uuid",
    "grid_row": 350,
    "grid_col": 280,
    "rotation": 90,
    "flip_h": true
  },
  ...
]
```

Response: 200 with updated panel list.

Behavior:
- Single database transaction for atomicity
- Validates all panel_ids belong to the specified mosaic
- Returns 404 if any panel_id is not found in the mosaic
- Accepts partial updates (only provided fields are changed per panel)

### Schema updates

- MosaicUpdate (Pydantic): add optional rotation_angle: float field. Used by existing PUT /{mosaic_id} endpoint.
- New MosaicPanelBatchUpdate schema: list of panel updates with panel_id + optional grid_row, grid_col, rotation, flip_h.

### Reinterpretation of grid_row/grid_col

These columns (Integer, nullable) now store pixel coordinates instead of cell indices. The column type does not change, but the `pixel_coords` flag migration is required to distinguish old mosaics (cell indices) from new/converted mosaics (pixel coordinates). The column names become slightly misleading but changing them would require a rename migration and break backward compatibility for no functional gain.

## Frontend Changes

### New dependency

- `konva` npm package (~150KB minified). No SolidJS wrapper needed.

### Remove dependency

- `@thisbeyond/solid-dnd` (v0.7.5). Verify it is not used elsewhere in the codebase before removing.

### New component: KonvaMosaicArranger.tsx

Location: frontend/src/components/mosaics/KonvaMosaicArranger.tsx

Features:
- Drag with 20px grid snap (real-time on dragmove)
- Per-tile rotate (0, 90, 180, 270 degrees) via toolbar button or right-click
- Per-tile flip horizontal via toolbar button
- Global mosaic rotation slider (-180 to +180 degrees)
- Zoom via mouse wheel (centered on pointer) and +/- buttons
- Pan via drag on empty canvas space
- Fit to View button: auto-scales and centers all tiles in the viewport
- Tile swap: when dropping on another tile, swap their positions
- Two Konva layers: background grid lines (non-interactive) and tile layer
- Selection: click tile to select (blue border highlight), click empty space to deselect
- Labels: panel name and dimensions displayed on each tile
- State badge: rotation/flip indicator per tile (e.g., "R90 FH")

### Delete: MosaicPanelArranger.tsx

Replaced entirely by KonvaMosaicArranger.tsx. Remove the file and all imports.

### Update: client.ts

Add:
- `batchUpdateMosaicPanels(mosaicId, panels)`: PUT to /{mosaic_id}/panels/batch
- Update `updateMosaic()` to accept rotation_angle in the body

### Update: MosaicDetailPage.tsx

- Replace MosaicPanelArranger import with KonvaMosaicArranger
- Pass rotation_angle from mosaic data to the new component
- Wire up the save callback for batch updates

## Canvas Feature Details

### Grid snapping

Snap increment: 20px (configurable constant). Applied during dragmove:
```
node.x(Math.round(node.x() / SNAP) * SNAP)
node.y(Math.round(node.y() / SNAP) * SNAP)
```

Background grid lines drawn on a separate non-interactive layer at the same increment. Grid lines only re-render on zoom/pan changes, not during tile drag.

### Global rotation

All tiles live inside a single Konva.Group. Rotating the Group rotates all children. Konva automatically transforms pointer coordinates into the Group's local space, so drag within a rotated group works correctly without manual coordinate math.

The rotation angle is stored on the Mosaic model (rotation_angle column) and applied to the Group on load.

### Zoom and pan

- Zoom: Stage.scaleX/scaleY, centered on pointer position. Range: 0.1x to 3.0x.
- Pan: Stage.x/Stage.y, updated on pointermove when dragging empty canvas.
- Fit to View: calculate bounding box of all tiles, compute scale to fit viewport with 40px padding, center the Stage.

### Tile overlap detection and swap

On dragend, check if the dropped tile's snapped position overlaps any other tile (bounding box intersection).

If the tile is dragged to empty space (no overlap), it simply moves there with no swap.

If overlap is detected, only two-tile swaps are supported. When the dropped position overlaps multiple tiles, swap with the tile whose center is closest to the drop point. The swap procedure:
1. Store the closest overlapping tile's position
2. Move that tile to the dragged tile's original position (animated, 200ms)
3. Place the dragged tile at the target position

### Tile aspect ratios

Each tile's Konva.Image dimensions match the source thumbnail's actual width/height. No forced aspect ratio. The panel's thumbnail dimensions come from the backend (or are measured from the loaded image).

If a thumbnail fails to load, use a placeholder rectangle of 300x300 with the panel label centered. This prevents layout breakage from missing images.

## Testing

- Backend: pytest for the new batch endpoint (happy path, partial update, invalid panel_id, cross-mosaic panel_id rejection)
- Backend: test rotation_angle persistence on mosaic update
- Frontend: manual testing (no frontend test suite exists yet)
- Migration: test the small-integer-to-pixel conversion logic with a mosaic that has grid_row/grid_col values of 0/1/2

## Rollout

### Phase 1: Backend
- Alembic migration adding rotation_angle and pixel_coords columns (single migration, defensive helpers)
- Batch endpoint: PUT /{mosaic_id}/panels/batch
- Schema updates: MosaicUpdate gains rotation_angle and pixel_coords; new MosaicPanelBatchUpdate schema

### Phase 2: Frontend
- Install konva npm package
- Build KonvaMosaicArranger component
- Wire into MosaicDetailPage (replace MosaicPanelArranger import, pass rotation_angle/pixel_coords, connect batch save callback)

### Phase 3: Cleanup
- Remove MosaicPanelArranger.tsx
- Remove @thisbeyond/solid-dnd dependency from package.json (confirmed: it is only used in MosaicPanelArranger.tsx, not elsewhere in the codebase)

### Phase 4: Testing
- Test with existing mosaics to verify legacy position migration (pixel_coords false to true conversion)
- Test batch save round-trip (drag, rotate, flip, reload)
- Test global rotation persistence across page loads
