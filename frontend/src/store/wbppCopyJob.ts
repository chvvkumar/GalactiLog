// Module-level state for the WBPP in-browser copy, so the copy survives the
// export modal closing: the modal drives the copy through startWbppCopy and
// renders from these accessors, and the job monitor shows the same state on
// every page. The copy still dies with the tab (File System Access API is
// tab-bound), which is why a beforeunload guard is registered while running.
import { createSignal } from "solid-js";
import {
  runBrowserCopy,
  CopyCancelledError,
  type PermState,
} from "../lib/wbppBrowserCopy";
import { showToast } from "../components/Toast";
import { getErrorMessage } from "../utils/errors";
import type { ActiveJob, WbppCopyOperation } from "../api/types";

const [running, setRunning] = createSignal(false);
const [done, setDone] = createSignal(0);
const [total, setTotal] = createSignal(0);
const [label, setLabel] = createSignal("");
const [error, setError] = createSignal<string | null>(null);
const [finished, setFinished] = createSignal<number | null>(null);
const [targetName, setTargetName] = createSignal("");
let startedAt = 0;
let abortController: AbortController | null = null;

// preventDefault + returnValue is the portable way to request the browser's
// generic "leave site?" confirmation while a copy is in flight.
function onBeforeUnload(e: BeforeUnloadEvent): void {
  e.preventDefault();
  e.returnValue = "";
}

export interface StartWbppCopyArgs {
  rootHandle: any;
  destHandle: any;
  operations: WbppCopyOperation[];
  exclusions: string[];
  excludedSourceRelatives: string[];
  targetName: string;
  onPermission?: (which: "source" | "dest", state: PermState) => void;
}

export async function startWbppCopy(args: StartWbppCopyArgs): Promise<void> {
  if (running()) {
    // The modal has its own pre-check, but future callers (e.g. the job
    // monitor) have no such guard, so a second start must not fail silently.
    showToast("A WBPP copy is already running. Stop it first.", "error", 0);
    return;
  }
  setError(null);
  setFinished(null);
  setDone(0);
  setTotal(0);
  setLabel("");
  setTargetName(args.targetName);
  startedAt = Date.now();
  abortController = new AbortController();
  setRunning(true);
  window.addEventListener("beforeunload", onBeforeUnload);
  try {
    const result = await runBrowserCopy(args.rootHandle, args.destHandle, {
      operations: args.operations,
      exclusions: args.exclusions,
      excludedSourceRelatives: args.excludedSourceRelatives,
      onProgress: (d, t, l) => {
        setDone(d);
        setTotal(t);
        setLabel(l);
      },
      onPermission: args.onPermission,
      signal: abortController.signal,
    });
    setFinished(result.copied);
    showToast(
      `Copied ${result.copied} file${result.copied !== 1 ? "s" : ""} to ${result.destinationName}`,
    );
  } catch (e: unknown) {
    if (!(e instanceof CopyCancelledError)) {
      const msg = getErrorMessage(e, "Browser copy failed.");
      setError(msg);
      // Toast too: the modal that started the copy may be long closed.
      showToast(msg, "error", 0);
    }
  } finally {
    setRunning(false);
    abortController = null;
    window.removeEventListener("beforeunload", onBeforeUnload);
  }
}

export function stopWbppCopy(): void {
  abortController?.abort();
}

export const wbppCopyRunning = running;
export const wbppCopyDone = done;
export const wbppCopyTotal = total;
export const wbppCopyLabel = label;
export const wbppCopyError = error;
export const wbppCopyFinished = finished;

export function clearWbppCopyError(): void {
  setError(null);
}

export const wbppCopyActiveJob = (): ActiveJob | null =>
  running()
    ? {
        id: "wbpp-copy",
        category: "wbpp_copy",
        label: `WBPP copy: ${targetName()}`,
        subLabel:
          total() > 0
            ? `${done().toLocaleString()} / ${total().toLocaleString()} files`
            : "Counting files",
        progress: total() > 0 ? Math.min(1, done() / total()) : undefined,
        startedAt,
        cancelable: true,
        onCancel: async () => stopWbppCopy(),
      }
    : null;
