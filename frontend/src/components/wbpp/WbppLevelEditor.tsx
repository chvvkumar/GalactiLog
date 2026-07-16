import { For, Show, type JSX } from "solid-js";
import type { WbppSessionPreview, WbppFolderLevel } from "../../api/types";
import { joinRoot, lastSegment } from "./paths";

export interface WbppLevelEditorProps {
  session: WbppSessionPreview;
  chosenIndex: number;
  onSelect: (index: number) => void;
  libraryRoot: string;
  /**
   * Path separator to render with. Owned by the parent, which resolves it from
   * the pinned OS preference before falling back to the root's own shape. The
   * editor must not re-derive it: the plan's destinations are written with the
   * parent's separator, and two derivations of one fact drift.
   */
  separator: string;
}

/**
 * The cost of a level is what it drags along: frames from other sessions or
 * other targets that live under the same folder.
 */
function costParts(level: WbppFolderLevel): string[] {
  const parts: string[] = [];
  const dates = level.other_dates?.length ?? 0;
  const targets = level.other_targets?.length ?? 0;
  if (dates) parts.push(`+${dates} other session${dates !== 1 ? "s" : ""}`);
  if (targets) parts.push(`+${targets} other target${targets !== 1 ? "s" : ""}`);
  return parts;
}

/** Full names stay as hover detail so the row itself can stay quantified. */
function rowTitle(level: WbppFolderLevel): string {
  const detail: string[] = [];
  if (level.other_targets?.length) detail.push(`other targets: ${level.other_targets.join(", ")}`);
  if (level.other_dates?.length) detail.push(`other dates: ${level.other_dates.join(", ")}`);
  return detail.length ? `${level.path}\nAlso contains ${detail.join("; ")}` : level.path;
}

export default function WbppLevelEditor(props: WbppLevelEditorProps): JSX.Element {
  const groupName = () => `wbpp-level-${props.session.session_date}`;
  const sep = () => props.separator;

  return (
    <div class="flex flex-col gap-2">
      <p class="text-tiny text-theme-text-tertiary">
        Pick the folder to copy. Each folder sits inside the one above it.
      </p>

      <Show
        when={props.session.levels.length > 0}
        fallback={
          <p class="text-tiny text-theme-text-tertiary">No frames found for this session.</p>
        }
      >
        {/* The library root anchors the list: it fixes the top of the tree at a
            place the user recognises, so the rows below read as steps into it
            rather than an unexplained ordering. Not selectable, hence not a row
            in the radiogroup. */}
        <p
          class="flex items-center gap-2 py-1.5 pr-2 font-mono text-xs text-theme-text-tertiary truncate"
          style={{ "padding-left": "8px" }}
          title={props.libraryRoot}
        >
          {props.libraryRoot}
        </p>

        <div role="radiogroup" aria-label={`Folder level for ${props.session.session_date}`}>
          <For each={props.session.levels}>
            {(level, i) => {
              const selected = () => props.chosenIndex === i();
              const cost = () => costParts(level);
              return (
                <label
                  class={`flex items-center gap-2 py-1.5 pr-2 cursor-pointer rounded-[var(--radius-sm)] hover:bg-theme-hover ${
                    selected() ? "bg-theme-elevated" : ""
                  }`}
                  style={{ "padding-left": `${8 + (i() + 1) * 14}px` }}
                  title={rowTitle(level)}
                >
                  <input
                    type="radio"
                    class="sr-only"
                    name={groupName()}
                    value={i()}
                    checked={selected()}
                    onChange={() => props.onSelect(i())}
                  />
                  {/* Containment made visible: the elbow points back at the row
                      above, which is this folder's parent. */}
                  <span aria-hidden="true" class="shrink-0 text-theme-text-tertiary font-mono">
                    &#9492;
                  </span>
                  <span
                    aria-hidden="true"
                    class={`shrink-0 w-3.5 h-3.5 rounded-full border flex items-center justify-center ${
                      selected() ? "border-theme-accent" : "border-theme-border"
                    }`}
                  >
                    <Show when={selected()}>
                      <span class="w-1.5 h-1.5 rounded-full bg-theme-accent" />
                    </Show>
                  </span>

                  <span
                    class={`font-mono text-xs truncate ${
                      selected() ? "text-theme-text-primary" : "text-theme-text-secondary"
                    }`}
                  >
                    {lastSegment(level.path)}
                  </span>

                  <span class="ml-auto shrink-0">
                    <Show when={cost().length > 0}>
                      <span
                        class={`text-micro tabular-nums text-theme-warning ${
                          selected()
                            ? "px-1.5 py-0.5 rounded-[var(--radius-sm)] bg-theme-warning/15 border border-theme-warning/30"
                            : ""
                        }`}
                      >
                        {cost().join(", ")}
                      </span>
                    </Show>
                  </span>
                </label>
              );
            }}
          </For>
        </div>

        <div class="overflow-x-auto">
          <p class="font-mono text-tiny text-theme-text-tertiary whitespace-nowrap">
            <span>{joinRoot(props.libraryRoot, sep())}</span>
            <For each={props.session.levels}>
              {(level, i) => (
                <>
                  <Show when={i() > 0}>
                    <span>{sep()}</span>
                  </Show>
                  <span
                    class={
                      props.chosenIndex === i() ? "text-theme-text-primary font-semibold" : undefined
                    }
                  >
                    {lastSegment(level.path)}
                  </span>
                </>
              )}
            </For>
          </p>
        </div>
      </Show>
    </div>
  );
}
