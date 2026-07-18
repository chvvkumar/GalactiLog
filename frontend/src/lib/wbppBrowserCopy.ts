// Client-side folder copy for WBPP staging using the File System Access API.
//
// The user grants a handle to their library root and a destination folder; the
// browser copies the selected session folders directly between local folders -
// no generated script, no server involvement in the byte transfer. Supported
// only in Chromium browsers over a secure context (HTTPS or localhost).

import type { WbppCopyOperation } from "../api/types";

// Handles are typed loosely: lib.dom may not declare showDirectoryPicker on all
// TS versions, so we avoid coupling to specific FileSystem* interfaces.
type DirHandle = any;

export type PermState = "granted" | "prompt" | "denied" | "unsupported";

export const HANDLE_KEYS = {
  source: "wbpp:source",
  dest: "wbpp:dest",
} as const;

export function isFsAccessSupported(): boolean {
  return (
    typeof window !== "undefined" &&
    window.isSecureContext &&
    "showDirectoryPicker" in window
  );
}

export class CopyCancelledError extends Error {
  constructor() {
    super("cancelled");
    this.name = "CopyCancelledError";
  }
}

// --- IndexedDB handle persistence (handles are structured-cloneable) ---

const DB_NAME = "galactilog-wbpp";
const STORE = "handles";

function idbOpen(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, 1);
    req.onupgradeneeded = () => req.result.createObjectStore(STORE);
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

export async function storeHandle(key: string, handle: DirHandle): Promise<void> {
  try {
    const db = await idbOpen();
    await new Promise<void>((resolve, reject) => {
      const tx = db.transaction(STORE, "readwrite");
      tx.objectStore(STORE).put(handle, key);
      tx.oncomplete = () => resolve();
      tx.onerror = () => reject(tx.error);
    });
  } catch {
    // Persistence is best-effort; ignore failures.
  }
}

export async function loadStoredHandle(key: string): Promise<DirHandle | undefined> {
  try {
    const db = await idbOpen();
    return await new Promise((resolve, reject) => {
      const tx = db.transaction(STORE, "readonly");
      const req = tx.objectStore(STORE).get(key);
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => reject(req.error);
    });
  } catch {
    return undefined;
  }
}

// --- Permissions + picking ---

export async function queryHandlePermission(handle: DirHandle, mode: "read" | "readwrite"): Promise<PermState> {
  if (!handle?.queryPermission) return "unsupported";
  try {
    return await handle.queryPermission({ mode });
  } catch {
    return "prompt";
  }
}

export async function requestHandlePermission(handle: DirHandle, mode: "read" | "readwrite"): Promise<PermState> {
  if (!handle?.requestPermission) return "unsupported";
  return await handle.requestPermission({ mode });
}

// Must be called from within a user gesture. Throws CopyCancelledError if the
// user dismisses the picker.
export async function pickDirectory(mode: "read" | "readwrite", id: string): Promise<DirHandle> {
  const picker = (window as any).showDirectoryPicker;
  try {
    return await picker({ mode, id });
  } catch (e: any) {
    if (e?.name === "AbortError") throw new CopyCancelledError();
    throw e;
  }
}

// --- Copy ---

// Build a component-level matcher mirroring the backend: each pattern is anchored
// to a full path component, and "*" becomes ".*". So "finals" excludes a "finals"
// folder but not "semifinals", and "*CALIBRATED" matches any "...CALIBRATED".
function makeExcluder(patterns: string[]): (name: string) => boolean {
  const regexes = patterns
    .map((p) => p.trim())
    .filter((p) => p.length > 0)
    .map((p) => {
      const escaped = p
        .replace(/[.+?^${}()|[\]\\]/g, "\\$&")
        .replace(/\*/g, ".*");
      return new RegExp(`^(${escaped})$`);
    });
  return (name: string) => regexes.some((r) => r.test(name));
}

async function resolveDir(root: DirHandle, relPath: string): Promise<DirHandle> {
  let h = root;
  for (const part of relPath.split("/").filter(Boolean)) {
    h = await h.getDirectoryHandle(part, { create: false });
  }
  return h;
}

async function countFiles(
  dir: DirHandle,
  isExcluded: (n: string) => boolean,
  excludedFiles: Set<string>,
  relPath: string,
): Promise<number> {
  let n = 0;
  for await (const entry of dir.values()) {
    if (entry.kind === "directory") {
      if (isExcluded(entry.name)) continue;
      const childRel = relPath ? `${relPath}/${entry.name}` : entry.name;
      n += await countFiles(entry, isExcluded, excludedFiles, childRel);
    } else {
      const fileRel = relPath ? `${relPath}/${entry.name}` : entry.name;
      // Quality-filter exclusion: skip the count too, so progress totals match
      // what actually copies.
      if (excludedFiles.has(fileRel)) continue;
      n += 1;
    }
  }
  return n;
}

// Concurrent file copies per run; benchmarked over SMB/2.5GbE, saturates the
// link at 8.
const POOL_SIZE = 8;

// 16 MB slices cut FileSystemWritableFileStream IPC round trips; benchmarked
// best vs pipeTo over SMB.
const CHUNK_SIZE = 16 * 1024 * 1024;

interface CopyWorkItem {
  srcEntry: DirHandle; // file handle
  destDir: DirHandle;
  name: string;
  label: string;
}

// Enumerates a source tree, creating each destination directory as it recurses
// (so every file's parent exists before the pool writes it) and appending one
// work item per file to `out`. The flat list lets a single pool span files
// across directories and operations, so small folders don't serialize.
async function collectCopyWork(
  src: DirHandle,
  dest: DirHandle,
  isExcluded: (n: string) => boolean,
  excludedFiles: Set<string>,
  relPath: string,
  label: string,
  out: CopyWorkItem[],
  signal?: AbortSignal,
): Promise<void> {
  for await (const entry of src.values()) {
    if (signal?.aborted) throw new CopyCancelledError();
    if (entry.kind === "directory") {
      if (isExcluded(entry.name)) continue;
      const childRel = relPath ? `${relPath}/${entry.name}` : entry.name;
      const child = await dest.getDirectoryHandle(entry.name, { create: true });
      await collectCopyWork(entry, child, isExcluded, excludedFiles, childRel, label, out, signal);
    } else {
      const fileRel = relPath ? `${relPath}/${entry.name}` : entry.name;
      // Quality-filter exclusion: skip both the copy and the progress callback.
      if (excludedFiles.has(fileRel)) continue;
      out.push({ srcEntry: entry, destDir: dest, name: entry.name, label });
    }
  }
}

async function copyFile(item: CopyWorkItem, signal: AbortSignal): Promise<void> {
  const file = await item.srcEntry.getFile();
  const fh = await item.destDir.getFileHandle(item.name, { create: true });
  const writable = await fh.createWritable();
  // Read the file in CHUNK_SIZE slices rather than pipeTo: fewer, larger
  // writes cut IPC round trips and benchmark faster over SMB. On abort or
  // failure the writable is aborted so no half-written .crswap files linger.
  try {
    for (let off = 0; off < file.size; off += CHUNK_SIZE) {
      if (signal.aborted) throw new CopyCancelledError();
      const buf = await file.slice(off, off + CHUNK_SIZE).arrayBuffer();
      await writable.write(buf);
    }
    await writable.close();
  } catch (e) {
    try {
      await writable.abort();
    } catch {
      // Best-effort cleanup; surface the original error.
    }
    throw e;
  }
}

// Runs the work items through a bounded pool of POOL_SIZE workers. Any file
// failure (or the caller's signal) aborts the pool's own signal, which stops
// new files from starting and aborts in-flight writables; the run only rejects
// after every worker has settled.
async function runCopyPool(
  items: CopyWorkItem[],
  onFile: (item: CopyWorkItem) => void,
  signal?: AbortSignal,
): Promise<void> {
  const pool = new AbortController();
  const onOuterAbort = () => pool.abort();
  if (signal?.aborted) pool.abort();
  signal?.addEventListener("abort", onOuterAbort);
  let failed = false;
  let firstError: unknown;
  let next = 0;
  const worker = async (): Promise<void> => {
    while (next < items.length) {
      if (pool.signal.aborted) return;
      const item = items[next++];
      try {
        await copyFile(item, pool.signal);
      } catch (e) {
        if (!failed && !pool.signal.aborted) {
          failed = true;
          firstError = e;
        }
        pool.abort();
        return;
      }
      onFile(item);
    }
  };
  try {
    await Promise.all(Array.from({ length: Math.min(POOL_SIZE, items.length) }, worker));
  } finally {
    signal?.removeEventListener("abort", onOuterAbort);
  }
  if (signal?.aborted) throw new CopyCancelledError();
  if (failed) throw firstError;
}

export interface BrowserCopyResult {
  copied: number;
  destinationName: string;
}

export interface BrowserCopyOptions {
  operations: WbppCopyOperation[];
  exclusions: string[];
  // Quality-filter exclude set: fits-root-relative POSIX paths of LIGHT frames to
  // omit from the copy. Empty when the filter is off (whole-folder copy).
  excludedSourceRelatives: string[];
  onProgress: (done: number, total: number, label: string) => void;
  /**
   * Reports what each permission request actually returned, as it returns -- including
   * the "denied" that then throws. Without it the caller can only infer permission
   * state from success, so a denial leaves its UI showing the stale prior state with
   * no way to reach "denied".
   */
  onPermission?: (which: "source" | "dest", state: PermState) => void;
  signal?: AbortSignal;
}

// Copies each operation's source folder (resolved relative to rootHandle) into a
// same-named entry under destHandle. Both handles must already be chosen; this
// ensures read/write permission (prompting if needed - call from a user gesture).
// Throws CopyCancelledError if aborted via the signal.
export async function runBrowserCopy(
  rootHandle: DirHandle,
  destHandle: DirHandle,
  opts: BrowserCopyOptions,
): Promise<BrowserCopyResult> {
  // These two requests stay the first awaits after the caller's synchronous click
  // setup: the API only honours a permission prompt inside the user gesture that
  // triggered it, so nothing may be awaited before them.
  const srcPerm = await requestHandlePermission(rootHandle, "read");
  opts.onPermission?.("source", srcPerm);
  if (srcPerm === "denied") {
    throw new Error("Read permission for the library folder was denied.");
  }
  const destPerm = await requestHandlePermission(destHandle, "readwrite");
  opts.onPermission?.("dest", destPerm);
  if (destPerm === "denied") {
    throw new Error("Write permission for the destination folder was denied.");
  }

  const isExcluded = makeExcluder(opts.exclusions);
  const excludedFiles = new Set(opts.excludedSourceRelatives);

  // Resolve every source folder up front so a wrong root fails before any copy.
  // sourceRelative seeds the per-file relative path used to match the exclude set.
  const resolved: { src: DirHandle; destDir: DirHandle; label: string; sourceRelative: string }[] = [];
  for (const op of opts.operations) {
    let src: DirHandle;
    try {
      src = await resolveDir(rootHandle, op.source_relative);
    } catch {
      throw new Error(
        `Could not find "${op.source_relative}" under the selected library folder. ` +
          `Make sure you picked your library root (the folder that mirrors the server's FITS data root).`,
      );
    }
    const destDir = await destHandle.getDirectoryHandle(op.dest_entry, { create: true });
    resolved.push({ src, destDir, label: op.session_date, sourceRelative: op.source_relative });
  }

  let total = 0;
  for (const r of resolved) total += await countFiles(r.src, isExcluded, excludedFiles, r.sourceRelative);

  // One flat work list across every operation, so the pool stays full even
  // when individual session folders hold only a few files.
  const work: CopyWorkItem[] = [];
  for (const r of resolved) {
    await collectCopyWork(r.src, r.destDir, isExcluded, excludedFiles, r.sourceRelative, r.label, work, opts.signal);
  }

  let done = 0;
  await runCopyPool(
    work,
    (item) => {
      done += 1;
      opts.onProgress(done, total, `${item.label}: ${item.name}`);
    },
    opts.signal,
  );

  return { copied: done, destinationName: destHandle.name };
}
