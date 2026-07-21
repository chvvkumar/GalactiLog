import { Show, type JSX } from "solid-js";
import Button from "../ui/Button";
import { formatBytes } from "../../utils/format";

/**
 * Why a copy cannot start, in the order the user must resolve them. The parent
 * decides; the footer only renders. Null means a copy can proceed.
 *
 * Folded together with what used to be a separate `copyReady` boolean: readiness
 * IS the absence of a blocker, so deriving both from one value means the label and
 * the disabled state cannot drift into disagreeing about whether the click works.
 */
export type CopyBlocker = "destination" | "source" | "permission";

export interface WbppFooterProps {
  frameCount: number;
  folderCount: number;
  sizeBytes: number | null;
  /** Where the in-browser copy writes: the destination handle's name, or null if unchosen. */
  destination: string | null;
  /**
   * Where a generated script writes: the staging root. A DIFFERENT place from
   * `destination`, so it gets its own line -- the summary's frame/byte totals
   * describe the transfer, and either route can perform it.
   */
  scriptDestination: string | null;
  permissionGranted: boolean;
  /**
   * What stops a copy from starting, or null when one can proceed. Drives both the
   * primary's disabled state and what it says while disabled, so the button can
   * never name an action that is not the actual blocker.
   */
  blockedBy: CopyBlocker | null;
  canBrowserCopy: boolean;
  copying: boolean;
  copyProgress: { done: number; total: number; speed: string } | null;
  onCopy: () => void;
  onStop: () => void;
  scriptMenu: JSX.Element;
}

// The primary action lives here, pinned to the bottom of the scrolling panel, so
// it never scrolls out of reach and always sits beside a statement of what the
// click is about to do. `modal-surface` is repeated on the sticky element so the
// scrolling content does not bleed through it (same technique as
// ReleaseNotesModal's sticky header).
export default function WbppFooter(props: WbppFooterProps): JSX.Element {
  // `sizeBytes === null` means the total is genuinely unknown: the backend sends
  // `frame_bytes: null` rather than a partial sum when any frame's size is
  // unrecorded. Render the em-dash placeholder — never a 0 B or a partial total,
  // which would present an undercount as fact.
  const sizeLabel = () => (props.sizeBytes === null ? "—" : formatBytes(props.sizeBytes));

  const frames = () => props.frameCount.toLocaleString();

  const progressText = () => {
    const p = props.copyProgress;
    if (!p) return "Copying...";
    if (p.total <= 0) return "Scanning...";
    // Speed replaces the per-file name: a filename flickering 8x per second is
    // unreadable, while the windowed rate is the number the user actually wants.
    return p.speed ? `${p.done} / ${p.total} · ${p.speed}` : `${p.done} / ${p.total}`;
  };

  /**
   * Every label names the user's next move, so a disabled primary states its own
   * blocker instead of a plausible-looking action that is not it. "Grant access and
   * copy" beside a missing source folder named the wrong step: nothing about
   * granting access was what stood in the way.
   *
   * A denied permission is recoverable only by picking the folder again -- once
   * refused, the browser will not re-prompt for that handle, so the picker is the
   * way back. The label points at it rather than restating the refusal.
   */
  const primaryLabel = () => {
    if (props.copying) return progressText();
    switch (props.blockedBy) {
      case "destination":
        return "Choose a destination";
      case "source":
        return "Choose a source folder";
      case "permission":
        return "Access denied. Choose the folder again.";
    }
    if (!props.permissionGranted) return "Grant access and copy";
    return `Copy ${frames()} frames`;
  };

  return (
    <div class="modal-surface sticky bottom-0 border-t border-theme-border px-4 py-3 flex items-center justify-between gap-4">
      <div class="min-w-0">
        <div class="text-xs text-theme-text-secondary tabular-nums">
          {frames()} frames · {props.folderCount} folder
          {props.folderCount !== 1 ? "s" : ""} · {sizeLabel()}
        </div>
        {/* Two routes, two destinations. Each is labelled with the route that
            writes there, so "→ MyFolder" can never be read as the script's
            output path (or the reverse). */}
        <Show when={props.destination !== null}>
          <div class="text-tiny font-mono text-theme-text-tertiary truncate">
            <span class="font-sans">Copy </span>→ {props.destination}
          </div>
        </Show>
        <Show when={props.scriptDestination !== null}>
          <div
            class="text-tiny font-mono text-theme-text-tertiary truncate"
            title={props.scriptDestination ?? undefined}
          >
            <span class="font-sans">Script </span>→ {props.scriptDestination}
          </div>
        </Show>
      </div>

      <div class="flex items-center gap-2 shrink-0">
        <Show when={props.permissionGranted && props.canBrowserCopy && !props.copying}>
          <span class="text-micro text-theme-text-tertiary bg-theme-elevated border border-theme-border rounded-[var(--radius-sm)] px-2 py-0.5">
            Browser access ready
          </span>
        </Show>

        {props.scriptMenu}

        <Show
          when={props.canBrowserCopy}
          fallback={
            <p class="text-tiny text-theme-text-tertiary max-w-[22rem]">
              In-browser copy needs a Chromium browser (Chrome/Edge) over HTTPS or localhost.
              Use "Generate script" to download a copy script instead.
            </p>
          }
        >
          <Show when={props.copying}>
            <Button variant="secondary" size="sm" onClick={() => props.onStop()}>
              Stop
            </Button>
          </Show>
          <Button
            variant="primary"
            size="sm"
            class="max-w-[24rem] truncate"
            onClick={() => props.onCopy()}
            disabled={props.blockedBy !== null || props.copying}
          >
            {primaryLabel()}
          </Button>
        </Show>
      </div>
    </div>
  );
}
