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
const [speed, setSpeed] = createSignal("");
const [error, setError] = createSignal<string | null>(null);
const [finished, setFinished] = createSignal<number | null>(null);
const [targetName, setTargetName] = createSignal("");
let startedAt = 0;
let abortController: AbortController | null = null;

// --- Transfer rate ---
//
// The rate is windowed over the last RATE_WINDOW_MS of per-file completions so
// the display tracks the current link speed rather than averaging over the
// whole run (which would smear a slow start across an hour-long copy). Until
// the window has filled, the cumulative average is used: dividing a partial
// window's bytes by the full span would understate the rate.
const RATE_WINDOW_MS = 3000;
let rateSamples: { t: number; bytes: number }[] = [];
let bytesCopied = 0;

function formatRate(bytesPerSec: number): string {
  const mbps = (bytesPerSec * 8) / 1e6;
  if (mbps >= 1000) return `${(mbps / 1000).toFixed(1)} Gbps`;
  return `${Math.round(mbps)} Mbps`;
}

// Records one completed file and returns the formatted current rate, or ""
// when no time has elapsed yet.
function recordFileBytes(bytes: number): string {
  const now = Date.now();
  bytesCopied += bytes;
  rateSamples.push({ t: now, bytes });
  const cutoff = now - RATE_WINDOW_MS;
  while (rateSamples.length > 0 && rateSamples[0].t < cutoff) rateSamples.shift();
  const elapsedMs = now - startedAt;
  if (elapsedMs < RATE_WINDOW_MS) {
    return elapsedMs > 0 ? formatRate((bytesCopied * 1000) / elapsedMs) : "";
  }
  const windowBytes = rateSamples.reduce((sum, s) => sum + s.bytes, 0);
  return formatRate((windowBytes * 1000) / RATE_WINDOW_MS);
}

// --- Tab title mirror ---
//
// While a copy runs the progress is mirrored into document.title, so a
// backgrounded tab still shows how far along the copy is. Lives here rather
// than in a component because the copy survives the modal closing: the store
// is the one lifecycle that spans the whole job. The original title is
// captured on the first tick and restored when the run settles (success,
// failure, or cancel); capturing only while unset means a later run recaptures
// the clean title instead of nesting prefixes.
let originalTitle: string | null = null;

function updateTabTitle(d: number, t: number, rate: string): void {
  if (typeof document === "undefined") return;
  if (originalTitle === null) originalTitle = document.title;
  const prefix = rate ? `${d}/${t} · ${rate}` : `${d}/${t}`;
  document.title = `${prefix} — ${originalTitle}`;
}

function restoreTabTitle(): void {
  if (typeof document === "undefined") return;
  if (originalTitle !== null) {
    document.title = originalTitle;
    originalTitle = null;
  }
}

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
  setSpeed("");
  rateSamples = [];
  bytesCopied = 0;
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
      onProgress: (d, t, _label, bytes) => {
        setDone(d);
        setTotal(t);
        const rate = recordFileBytes(bytes);
        setSpeed(rate);
        updateTabTitle(d, t, rate);
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
    restoreTabTitle();
    window.removeEventListener("beforeunload", onBeforeUnload);
  }
}

export function stopWbppCopy(): void {
  abortController?.abort();
}

export const wbppCopyRunning = running;
export const wbppCopyDone = done;
export const wbppCopyTotal = total;
export const wbppCopySpeed = speed;
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
            ? `${done().toLocaleString()} / ${total().toLocaleString()} files${speed() ? ` · ${speed()}` : ""}`
            : "Counting files",
        progress: total() > 0 ? Math.min(1, done() / total()) : undefined,
        startedAt,
        cancelable: true,
        onCancel: async () => stopWbppCopy(),
      }
    : null;
