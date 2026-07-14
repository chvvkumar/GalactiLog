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

async function copyDir(
  src: DirHandle,
  dest: DirHandle,
  isExcluded: (n: string) => boolean,
  excludedFiles: Set<string>,
  relPath: string,
  onFile: (name: string) => void,
  signal?: AbortSignal,
): Promise<void> {
  for await (const entry of src.values()) {
    if (signal?.aborted) throw new CopyCancelledError();
    if (entry.kind === "directory") {
      if (isExcluded(entry.name)) continue;
      const childRel = relPath ? `${relPath}/${entry.name}` : entry.name;
      const child = await dest.getDirectoryHandle(entry.name, { create: true });
      await copyDir(entry, child, isExcluded, excludedFiles, childRel, onFile, signal);
    } else {
      const fileRel = relPath ? `${relPath}/${entry.name}` : entry.name;
      // Quality-filter exclusion: skip both the copy and the progress callback.
      if (excludedFiles.has(fileRel)) continue;
      const file = await entry.getFile();
      const fh = await dest.getFileHandle(entry.name, { create: true });
      const writable = await fh.createWritable();
      // Stream the file rather than buffering it, so large FITS frames don't
      // load fully into memory.
      await file.stream().pipeTo(writable);
      onFile(entry.name);
    }
  }
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
  if ((await requestHandlePermission(rootHandle, "read")) === "denied") {
    throw new Error("Read permission for the library folder was denied.");
  }
  if ((await requestHandlePermission(destHandle, "readwrite")) === "denied") {
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

  let done = 0;
  for (const r of resolved) {
    await copyDir(
      r.src,
      r.destDir,
      isExcluded,
      excludedFiles,
      r.sourceRelative,
      (name) => {
        done += 1;
        opts.onProgress(done, total, `${r.label}: ${name}`);
      },
      opts.signal,
    );
  }

  return { copied: done, destinationName: destHandle.name };
}
