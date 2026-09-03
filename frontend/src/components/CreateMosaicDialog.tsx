import { Component, For, Show, createResource, createSignal } from "solid-js";
import Dialog from "./Dialog";
import Button from "./ui/Button";
import IconButton from "./ui/IconButton";
import { showToast } from "./Toast";
import { ApiError } from "../api/unwrap";
import { getErrorMessage } from "../utils/errors";
import {
  mosaicsFromSessionsApi,
  type CreateMosaicFromSessionsResponse,
} from "../api/mosaicsFromSessions";

interface Props {
  targetId: string;
  targetName: string;
  /** Selected session dates (YYYY-MM-DD). */
  dates: string[];
  onClose: () => void;
  /** Called after a successful create/add; the caller closes and navigates. */
  onCreated: (mosaic: CreateMosaicFromSessionsResponse) => void;
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** "2026-03-15" -> "Mar 2026". Parsed by hand so the browser timezone cannot
 * shift the date across a month boundary. */
function monthYear(date: string): string {
  const [y, m] = date.split("-");
  const name = MONTHS[Number(m) - 1];
  return name ? `${name} ${y}` : date;
}

/** Suffix matching the backend's suggestion naming: "Mar 2026" for a single
 * month, "Mar 2026 - May 2026" for a span. */
export function dateRangeSuffix(dates: string[]): string {
  const sorted = [...dates].sort();
  const first = monthYear(sorted[0]);
  const last = monthYear(sorted[sorted.length - 1]);
  return first === last ? first : `${first} - ${last}`;
}

const FIELD_CLASS =
  "text-sm px-2 py-1.5 bg-theme-base border border-theme-border rounded-[var(--radius-sm)] text-theme-text-primary focus:outline-none focus:border-theme-accent";

/**
 * Create a mosaic (or grow an existing one) from the sessions selected on the
 * target detail page. Each prefill row is one session_date x panel_label pair;
 * rows sharing the same non-empty label are grouped into one panel on submit.
 *
 * Name and per-row labels are derived from the prefill until the user edits
 * them (edits stored sparsely), so no effect is needed to seed signals.
 */
const CreateMosaicDialog: Component<Props> = (props) => {
  const [prefill] = createResource(() =>
    mosaicsFromSessionsApi.prefill(props.targetId, props.dates),
  );
  const rows = () => prefill()?.rows;

  const [mode, setMode] = createSignal<"new" | "existing">("new");
  const [mosaicId, setMosaicId] = createSignal("");
  const [submitting, setSubmitting] = createSignal(false);
  const [nameError, setNameError] = createSignal<string | null>(null);

  const suffix = dateRangeSuffix(props.dates);
  const [nameEdit, setNameEdit] = createSignal<string | null>(null);
  const name = () => nameEdit() ?? `${prefill()?.base_name ?? props.targetName} (${suffix})`;

  const [labelEdits, setLabelEdits] = createSignal<Record<number, string>>({});
  const label = (i: number) => labelEdits()[i] ?? rows()?.[i]?.panel_label ?? "";
  const setLabel = (i: number, value: string) =>
    setLabelEdits((prev) => ({ ...prev, [i]: value }));

  const allLabelsFilled = () => {
    const r = rows();
    return !!r && r.length > 0 && r.every((_, i) => label(i).trim() !== "");
  };

  const canSubmit = () =>
    !submitting() &&
    allLabelsFilled() &&
    (mode() === "new" ? name().trim() !== "" : mosaicId() !== "");

  /** Rows sharing a trimmed edited label become one panel. Each underlying
   * prefill row keeps its ORIGINAL prefill label so the backend can claim the
   * frames it was counted under. */
  const buildPanels = () => {
    const byLabel = new Map<string, { session_date: string; original_panel_label: string | null }[]>();
    (rows() ?? []).forEach((row, i) => {
      const panelLabel = label(i).trim();
      if (!panelLabel) return;
      const entries = byLabel.get(panelLabel) ?? [];
      entries.push({ session_date: row.session_date, original_panel_label: row.panel_label });
      byLabel.set(panelLabel, entries);
    });
    return [...byLabel.entries()].map(([panel_label, panelRows]) => ({
      panel_label,
      rows: panelRows,
    }));
  };

  const submit = async () => {
    if (!canSubmit()) return;
    setSubmitting(true);
    setNameError(null);
    try {
      const result = await mosaicsFromSessionsApi.create({
        mode: mode(),
        ...(mode() === "new" ? { name: name().trim() } : { mosaic_id: mosaicId() }),
        target_id: props.targetId,
        panels: buildPanels(),
      });
      props.onCreated(result);
    } catch (e: unknown) {
      if (e instanceof ApiError && e.status === 409 && mode() === "new") {
        setNameError(e.message);
      } else {
        showToast(getErrorMessage(e, "Failed to create mosaic"), "error");
      }
    } finally {
      setSubmitting(false);
    }
  };

  const existingDisabled = () => (prefill()?.mosaics.length ?? 0) === 0;

  return (
    <Dialog open aria-labelledby="create-mosaic-dialog-title" onClose={props.onClose}>
      <div
        class="bg-theme-surface border border-theme-border rounded-[var(--radius-md)] shadow-[var(--shadow-lg)] max-w-lg w-full mx-4 max-h-[85vh] flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        <div class="shrink-0 px-4 py-3 border-b border-theme-border flex items-start justify-between gap-4">
          <div class="min-w-0">
            <h2 id="create-mosaic-dialog-title" class="text-sm font-medium text-theme-text-primary">
              Create Mosaic
            </h2>
            <p class="text-tiny text-theme-text-secondary truncate">
              {props.targetName} · {props.dates.length} session{props.dates.length !== 1 ? "s" : ""}
            </p>
          </div>
          <IconButton onClick={props.onClose} aria-label="Close">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
              <line x1="6" y1="6" x2="18" y2="18" /><line x1="6" y1="18" x2="18" y2="6" />
            </svg>
          </IconButton>
        </div>

        <div class="flex-1 min-h-0 overflow-y-auto px-4 py-4 space-y-4">
          <Show when={prefill.loading}>
            <p class="text-xs text-theme-text-secondary">Loading sessions...</p>
          </Show>
          <Show when={prefill.error}>
            <div class="text-xs text-theme-error bg-theme-error/10 border border-theme-error/30 rounded-[var(--radius-sm)] px-3 py-2">
              {getErrorMessage(prefill.error, "Failed to load mosaic prefill")}
            </div>
          </Show>

          <Show when={rows()}>
            {(prefillRows) => (
              <>
                <div class="space-y-2">
                  <label class="flex items-center gap-2 cursor-pointer">
                    <input
                      type="radio"
                      name="create-mosaic-mode"
                      class="cursor-pointer"
                      checked={mode() === "new"}
                      onChange={() => setMode("new")}
                    />
                    <span class="text-sm text-theme-text-primary">New mosaic</span>
                  </label>
                  <Show when={mode() === "new"}>
                    <div class="pl-6 space-y-1">
                      <label class="block text-xs text-theme-text-secondary" for="create-mosaic-name">
                        Name
                      </label>
                      <input
                        id="create-mosaic-name"
                        type="text"
                        class={`${FIELD_CLASS} w-full ${nameError() ? "border-theme-error" : ""}`}
                        value={name()}
                        onInput={(e) => {
                          setNameError(null);
                          setNameEdit(e.currentTarget.value);
                        }}
                      />
                      <Show when={nameError()}>
                        <p class="text-xs text-theme-error">{nameError()}</p>
                      </Show>
                    </div>
                  </Show>
                  <label
                    class={`flex items-center gap-2 ${existingDisabled() ? "opacity-50 cursor-not-allowed" : "cursor-pointer"}`}
                    title={existingDisabled() ? "No existing mosaics include this target" : undefined}
                  >
                    <input
                      type="radio"
                      name="create-mosaic-mode"
                      class="cursor-pointer disabled:cursor-not-allowed"
                      disabled={existingDisabled()}
                      checked={mode() === "existing"}
                      onChange={() => setMode("existing")}
                    />
                    <span class="text-sm text-theme-text-primary">Add to existing</span>
                  </label>
                  <Show when={mode() === "existing"}>
                    <div class="pl-6 space-y-1">
                      <label class="block text-xs text-theme-text-secondary" for="create-mosaic-existing">
                        Mosaic
                      </label>
                      <select
                        id="create-mosaic-existing"
                        class={`${FIELD_CLASS} w-full cursor-pointer`}
                        value={mosaicId()}
                        onChange={(e) => setMosaicId(e.currentTarget.value)}
                      >
                        <option value="" disabled>Select a mosaic...</option>
                        <For each={prefill()?.mosaics ?? []}>
                          {(m) => <option value={m.id}>{m.name}</option>}
                        </For>
                      </select>
                    </div>
                  </Show>
                </div>

                <div class="space-y-1">
                  <div class="grid grid-cols-[1fr_auto_8rem] gap-x-3 items-center text-caption text-theme-text-tertiary uppercase tracking-wider px-1">
                    <span>Session</span>
                    <span class="text-right">Frames</span>
                    <span>Panel</span>
                  </div>
                  <For each={prefillRows()}>
                    {(row, i) => (
                      <div class="grid grid-cols-[1fr_auto_8rem] gap-x-3 items-center px-1 py-0.5">
                        <span class="text-sm text-theme-text-primary tabular-nums">
                          {row.session_date}
                        </span>
                        <span class="text-sm text-theme-text-secondary tabular-nums text-right">
                          {row.frame_count}
                        </span>
                        <input
                          type="text"
                          aria-label={`Panel label for ${row.session_date}`}
                          placeholder="e.g. Panel 1"
                          class={`${FIELD_CLASS} w-full`}
                          value={label(i())}
                          onInput={(e) => setLabel(i(), e.currentTarget.value)}
                        />
                      </div>
                    )}
                  </For>
                  <p class="text-tiny text-theme-text-secondary px-1">
                    Sessions with the same panel label are combined into one panel.
                  </p>
                </div>
              </>
            )}
          </Show>
        </div>

        <div class="shrink-0 px-4 py-3 border-t border-theme-border flex justify-end gap-2">
          <Button variant="secondary" size="sm" onClick={props.onClose} disabled={submitting()}>
            Cancel
          </Button>
          <Button variant="primary" size="sm" disabled={!canSubmit()} onClick={() => void submit()}>
            {submitting()
              ? "Saving..."
              : mode() === "new"
                ? "Create Mosaic"
                : "Add to Mosaic"}
          </Button>
        </div>
      </div>
    </Dialog>
  );
};

export default CreateMosaicDialog;
