// Client-side folder copy for WBPP staging using the File System Access API.
//
// The user grants a handle to their library root and a destination folder; the
// browser copies the selected session folders directly between local folders -
// no generated script, no server involvement in the byte transfer. Supported
// only in Chromium browsers over a secure context (HTTPS or localhost).

import type { WbppCopyOperation } from "../types";

// Handles are typed loosely: lib.dom may not declare showDirectoryPicker on all
// TS versions, so we avoid coupling to specific FileSystem* interfaces.
type DirHandle = any;

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

async function countFiles(dir: DirHandle, isExcluded: (n: string) => boolean): Promise<number> {
  let n = 0;
  for await (const entry of dir.values()) {
    if (entry.kind === "directory") {
      if (isExcluded(entry.name)) continue;
      n += await countFiles(entry, isExcluded);
    } else {
      n += 1;
    }
  }
  return n;
}

async function copyDir(
  src: DirHandle,
  dest: DirHandle,
  isExcluded: (n: string) => boolean,
  onFile: (name: string) => void,
  signal?: AbortSignal,
): Promise<void> {
  for await (const entry of src.values()) {
    if (signal?.aborted) throw new CopyCancelledError();
    if (entry.kind === "directory") {
      if (isExcluded(entry.name)) continue;
      const child = await dest.getDirectoryHandle(entry.name, { create: true });
      await copyDir(entry, child, isExcluded, onFile, signal);
    } else {
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
  onProgress: (done: number, total: number, label: string) => void;
  signal?: AbortSignal;
}

// Prompts for the library root and destination, then copies each operation's
// source folder into a same-named entry under the destination. Throws
// CopyCancelledError if the user cancels a picker or aborts mid-copy.
export async function runBrowserCopy(opts: BrowserCopyOptions): Promise<BrowserCopyResult> {
  const picker = (window as any).showDirectoryPicker;

  let root: DirHandle;
  let dest: DirHandle;
  try {
    root = await picker({ mode: "read", id: "wbpp-library" });
    dest = await picker({ mode: "readwrite", id: "wbpp-staging" });
  } catch (e: any) {
    if (e?.name === "AbortError") throw new CopyCancelledError();
    throw e;
  }

  if (dest.requestPermission) {
    const perm = await dest.requestPermission({ mode: "readwrite" });
    if (perm === "denied") {
      throw new Error("Write permission to the destination folder was denied.");
    }
  }

  const isExcluded = makeExcluder(opts.exclusions);

  // Resolve every source folder up front so a wrong root fails before any copy.
  const resolved: { src: DirHandle; destDir: DirHandle; label: string }[] = [];
  for (const op of opts.operations) {
    let src: DirHandle;
    try {
      src = await resolveDir(root, op.source_relative);
    } catch {
      throw new Error(
        `Could not find "${op.source_relative}" under the selected folder. ` +
          `Make sure you picked your library root (the folder that mirrors the server's FITS data root).`,
      );
    }
    const destDir = await dest.getDirectoryHandle(op.dest_entry, { create: true });
    resolved.push({ src, destDir, label: op.session_date });
  }

  let total = 0;
  for (const r of resolved) total += await countFiles(r.src, isExcluded);

  let done = 0;
  for (const r of resolved) {
    await copyDir(
      r.src,
      r.destDir,
      isExcluded,
      (name) => {
        done += 1;
        opts.onProgress(done, total, `${r.label}: ${name}`);
      },
      opts.signal,
    );
  }

  return { copied: done, destinationName: dest.name };
}
