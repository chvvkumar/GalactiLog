import { describe, it, expect, vi } from "vitest";

import { runBrowserCopy, CopyCancelledError } from "./wbppBrowserCopy";
import type { WbppCopyOperation } from "../api/types";

// --- Fake File System Access handles -----------------------------------------
//
// The other wbpp tests (wbppCopyJob.test.ts, WbppExportModal.test.tsx) mock
// runBrowserCopy itself, so no directory-handle fakes existed before this file.
// These fakes model just the surface runBrowserCopy touches: values(),
// getDirectoryHandle, getFileHandle, getFile() with .size/.slice().arrayBuffer()
// (the chunked copy path), createWritable() with write/close/abort, and
// requestPermission/queryPermission.

// A virtual file stands in for a large file without allocating its bytes: the
// fake File reports `virtualSize` and slice().arrayBuffer() returns zero-filled
// buffers of the sliced length.
interface VirtualFile {
  virtualSize: number;
}

type Tree = { [name: string]: Tree | Uint8Array | VirtualFile };

// jsdom's TextEncoder produces Uint8Arrays from another realm, so `instanceof
// Uint8Array` is false for them; ArrayBuffer.isView is cross-realm safe.
const isBytes = (v: Tree | Uint8Array | VirtualFile): v is Uint8Array => ArrayBuffer.isView(v);
const isVirtual = (v: Tree | Uint8Array | VirtualFile): v is VirtualFile =>
  !isBytes(v) && typeof (v as VirtualFile).virtualSize === "number";

interface Track {
  active: number;
  highWater: number;
  started: string[];
}

interface Ctrl {
  track: Track;
  // Awaited inside each file's FIRST slice().arrayBuffer() call before any
  // bytes are produced; keyed by the file's path relative to the source root.
  // Lets a test hold files "in flight" to observe concurrency, aborts, and
  // settling.
  gate?: (relPath: string) => Promise<void> | void;
  // Returning an Error makes that file's arrayBuffer() reject instead of
  // delivering bytes (a source read failure).
  fail?: (relPath: string) => Error | undefined;
}

function makeCtrl(overrides: Partial<Ctrl> = {}): Ctrl {
  return { track: { active: 0, highWater: 0, started: [] }, ...overrides };
}

function makeSourceFile(name: string, content: Uint8Array | VirtualFile, ctrl: Ctrl, rel: string) {
  const size = isBytes(content) ? content.length : content.virtualSize;
  let firstRead = true;
  return {
    kind: "file" as const,
    name,
    async getFile() {
      return {
        size,
        slice(start: number, end: number) {
          const s = Math.max(0, Math.min(start, size));
          const e = Math.max(s, Math.min(end, size));
          return {
            arrayBuffer: async (): Promise<ArrayBuffer> => {
              const isFirst = firstRead;
              firstRead = false;
              if (isFirst) {
                ctrl.track.active += 1;
                ctrl.track.highWater = Math.max(ctrl.track.highWater, ctrl.track.active);
                ctrl.track.started.push(rel);
              }
              try {
                if (isFirst) await ctrl.gate?.(rel);
                const err = ctrl.fail?.(rel);
                if (err) throw err;
                // Copy into a same-realm buffer (source bytes may come from
                // jsdom's TextEncoder realm).
                const out = new Uint8Array(e - s);
                if (isBytes(content)) out.set(content.subarray(s, e));
                return out.buffer;
              } finally {
                if (isFirst) ctrl.track.active -= 1;
              }
            },
          };
        },
      };
    },
  };
}

function makeSourceDir(name: string, tree: Tree, ctrl: Ctrl, rel = ""): any {
  return {
    kind: "directory" as const,
    name,
    async *values() {
      for (const [n, v] of Object.entries(tree)) {
        const childRel = rel ? `${rel}/${n}` : n;
        if (isBytes(v) || isVirtual(v)) yield makeSourceFile(n, v, ctrl, childRel);
        else yield makeSourceDir(n, v, ctrl, childRel);
      }
    },
    async getDirectoryHandle(n: string) {
      const v = tree[n];
      if (!v || isBytes(v) || isVirtual(v)) throw new Error(`NotFoundError: ${n}`);
      return makeSourceDir(n, v, ctrl, rel ? `${rel}/${n}` : n);
    },
    queryPermission: async () => "granted",
    requestPermission: async () => "granted",
  };
}

interface DestFileRec {
  kind: "file";
  name: string;
  chunks: Uint8Array[];
  writes: number;
  closed: boolean;
  aborted: boolean;
  writableCreated: boolean;
  createWritable(): Promise<any>;
}

function makeDestFile(name: string): DestFileRec {
  const rec: DestFileRec = {
    kind: "file",
    name,
    chunks: [],
    writes: 0,
    closed: false,
    aborted: false,
    writableCreated: false,
    async createWritable() {
      rec.writableCreated = true;
      return {
        async write(buf: ArrayBuffer) {
          rec.writes += 1;
          rec.chunks.push(new Uint8Array(buf));
        },
        async close() {
          rec.closed = true;
        },
        async abort() {
          rec.aborted = true;
        },
      };
    },
  };
  return rec;
}

function makeDestDir(name: string): any {
  const dirs = new Map<string, any>();
  const files = new Map<string, DestFileRec>();
  return {
    kind: "directory" as const,
    name,
    dirs,
    files,
    async getDirectoryHandle(n: string, opts?: { create?: boolean }) {
      if (!dirs.has(n)) {
        if (!opts?.create) throw new Error(`NotFoundError: ${n}`);
        dirs.set(n, makeDestDir(n));
      }
      return dirs.get(n);
    },
    async getFileHandle(n: string, opts?: { create?: boolean }) {
      if (!files.has(n)) {
        if (!opts?.create) throw new Error(`NotFoundError: ${n}`);
        files.set(n, makeDestFile(n));
      }
      return files.get(n);
    },
    queryPermission: async () => "granted",
    requestPermission: async () => "granted",
  };
}

function flattenDest(dir: any, prefix = ""): Map<string, string> {
  const out = new Map<string, string>();
  for (const [n, f] of dir.files as Map<string, DestFileRec>) {
    const total = f.chunks.reduce((acc, c) => acc + c.length, 0);
    const buf = new Uint8Array(total);
    let off = 0;
    for (const c of f.chunks) {
      buf.set(c, off);
      off += c.length;
    }
    out.set(prefix ? `${prefix}/${n}` : n, new TextDecoder().decode(buf));
  }
  for (const [n, d] of dir.dirs as Map<string, any>) {
    for (const [p, s] of flattenDest(d, prefix ? `${prefix}/${n}` : n)) out.set(p, s);
  }
  return out;
}

function collectDestFiles(dir: any): DestFileRec[] {
  const out: DestFileRec[] = [...(dir.files as Map<string, DestFileRec>).values()];
  for (const d of (dir.dirs as Map<string, any>).values()) out.push(...collectDestFiles(d));
  return out;
}

// --- Test helpers -------------------------------------------------------------

const b = (s: string) => new TextEncoder().encode(s);

const op = (sourceRelative: string, destEntry = sourceRelative.split("/").pop()!): WbppCopyOperation => ({
  source_relative: sourceRelative,
  dest_entry: destEntry,
  destination: `/staging/${destEntry}`,
  source: `/library/${sourceRelative}`,
  session_date: destEntry,
});

function deferred() {
  let resolve!: () => void;
  const promise = new Promise<void>((res) => {
    resolve = res;
  });
  return { promise, resolve };
}

const tick = () => new Promise<void>((res) => setTimeout(res, 0));

// Waits until track.started stops growing across a few macrotask turns, i.e.
// the copy has launched everything it is going to launch while gates hold.
async function waitForLaunchQuiescence(track: Track): Promise<void> {
  let prev = -1;
  let stable = 0;
  while (stable < 3) {
    await tick();
    if (track.started.length === prev) stable += 1;
    else {
      stable = 0;
      prev = track.started.length;
    }
  }
}

// Repeatedly opens every pending gate until the run settles; later files may
// create new gates after earlier ones release, so a single pass is not enough.
async function releaseUntilSettled(runP: Promise<unknown>, gates: Map<string, { resolve: () => void }>): Promise<void> {
  let settled = false;
  runP.then(
    () => {
      settled = true;
    },
    () => {
      settled = true;
    },
  );
  while (!settled) {
    for (const g of gates.values()) g.resolve();
    await tick();
  }
}

function baseOpts(operations: WbppCopyOperation[], extra: Partial<Parameters<typeof runBrowserCopy>[2]> = {}) {
  return {
    operations,
    exclusions: [],
    excludedSourceRelatives: [],
    onProgress: vi.fn(),
    ...extra,
  };
}

const MB = 1024 * 1024;

// --- Tests --------------------------------------------------------------------

describe("runBrowserCopy", () => {
  it("copies every file across nested directories; destination matches source names and bytes", async () => {
    const ctrl = makeCtrl();
    const root = makeSourceDir("library", {
      "2025-01-01": {
        LIGHT: { "a.fits": b("alpha-bytes"), "b.fits": b("bravo") },
        cal: { "flat.fits": b("flat-data") },
      },
      "2025-01-02": { "c.fits": b("charlie") },
    }, ctrl);
    const dest = makeDestDir("staging");

    const result = await runBrowserCopy(root, dest, baseOpts([op("2025-01-01"), op("2025-01-02")]));

    expect(result.copied).toBe(4);
    expect(result.destinationName).toBe("staging");
    const got = flattenDest(dest);
    expect(got).toEqual(
      new Map([
        ["2025-01-01/LIGHT/a.fits", "alpha-bytes"],
        ["2025-01-01/LIGHT/b.fits", "bravo"],
        ["2025-01-01/cal/flat.fits", "flat-data"],
        ["2025-01-02/c.fits", "charlie"],
      ]),
    );
    // Every writable the copy opened must be settled (closed after a full write).
    for (const f of collectDestFiles(dest)) {
      expect(f.closed).toBe(true);
      expect(f.aborted).toBe(false);
    }
  });

  it("runs files through a bounded pool: more than one in flight, never more than 8", async () => {
    // Gate every file's first arrayBuffer() so nothing finishes until we let
    // it; the high-water mark of files concurrently inside a read is the
    // observed pool width. A sequential implementation reads 1 here and fails
    // the lower bound; anything wider than POOL_SIZE=8 fails the upper bound.
    const gates = new Map<string, { promise: Promise<void>; resolve: () => void }>();
    const ctrl = makeCtrl({
      gate: (rel) => {
        const d = deferred();
        gates.set(rel, d);
        return d.promise;
      },
    });
    const tree: Tree = {};
    for (let i = 0; i < 12; i += 1) tree[`f${i}.fits`] = b(`data-${i}`);
    const root = makeSourceDir("library", { s1: tree }, ctrl);
    const dest = makeDestDir("staging");

    const runP = runBrowserCopy(root, dest, baseOpts([op("s1")]));
    runP.catch(() => {});

    await waitForLaunchQuiescence(ctrl.track);
    await releaseUntilSettled(runP, gates);
    const result = await runP;

    expect(result.copied).toBe(12);
    expect(ctrl.track.highWater).toBeGreaterThan(1);
    expect(ctrl.track.highWater).toBeLessThanOrEqual(8);
  });

  it("reports progress exactly once per file with a correct total, in any order", async () => {
    const ctrl = makeCtrl();
    const root = makeSourceDir("library", {
      s1: { "a.fits": b("a"), sub: { "b.fits": b("b"), "c.fits": b("c") } },
      s2: { "d.fits": b("d") },
    }, ctrl);
    const dest = makeDestDir("staging");
    const onProgress = vi.fn<(done: number, total: number, label: string, bytes: number) => void>();

    await runBrowserCopy(root, dest, baseOpts([op("s1"), op("s2")], { onProgress }));

    const calls = onProgress.mock.calls;
    expect(calls.length).toBe(4);
    // Every call carries the full total; done values are 1..N as a set,
    // regardless of completion order.
    for (const [, total] of calls) expect(total).toBe(4);
    const dones = calls.map(([done]) => done).sort((a, z) => a - z);
    expect(dones).toEqual([1, 2, 3, 4]);
    // Each file is reported exactly once (labels are "session: filename"), and
    // each report carries the completed file's byte size (every file here is
    // one byte of content).
    const names = ["a.fits", "b.fits", "c.fits", "d.fits"];
    for (const name of names) {
      const forFile = calls.filter(([, , label]) => label.endsWith(`: ${name}`));
      expect(forFile.length).toBe(1);
      expect(forFile[0][3]).toBe(1);
    }
  });

  it("abort mid-run: rejects with CopyCancelledError and starts no new files after abort", async () => {
    const gates = new Map<string, { promise: Promise<void>; resolve: () => void }>();
    const ctrl = makeCtrl({
      gate: (rel) => {
        const d = deferred();
        gates.set(rel, d);
        return d.promise;
      },
    });
    const tree: Tree = {};
    for (let i = 0; i < 10; i += 1) tree[`f${i}.fits`] = b(`data-${i}`);
    const root = makeSourceDir("library", { s1: tree }, ctrl);
    const dest = makeDestDir("staging");
    const controller = new AbortController();

    const runP = runBrowserCopy(root, dest, baseOpts([op("s1")], { signal: controller.signal }));
    runP.catch(() => {});

    await waitForLaunchQuiescence(ctrl.track);
    expect(ctrl.track.started.length).toBeGreaterThan(0);
    const startedAtAbort = ctrl.track.started.length;
    controller.abort();
    await releaseUntilSettled(runP, gates);

    await expect(runP).rejects.toMatchObject({ name: "CopyCancelledError" });
    await expect(runP).rejects.toBeInstanceOf(CopyCancelledError);
    // In-flight files may finish or be dropped, but nothing new launches once
    // the signal is aborted.
    expect(ctrl.track.started.length).toBe(startedAtAbort);
  });

  it("a single failing file rejects the run and leaves no dangling writable", async () => {
    const boom = new Error("boom");
    const ctrl = makeCtrl({
      fail: (rel) => (rel.endsWith("bad.fits") ? boom : undefined),
    });
    const root = makeSourceDir("library", {
      s1: { "ok1.fits": b("one"), "bad.fits": b("never"), "ok2.fits": b("two"), "ok3.fits": b("three") },
    }, ctrl);
    const dest = makeDestDir("staging");

    const runP = runBrowserCopy(root, dest, baseOpts([op("s1")]));
    await expect(runP).rejects.toThrow("boom");

    const destFiles = collectDestFiles(dest);
    const bad = destFiles.find((f) => f.name === "bad.fits");
    expect(bad).toBeDefined();
    // The failed read must abort the failing file's writable, not leave it open.
    expect(bad!.aborted).toBe(true);
    expect(bad!.closed).toBe(false);
    // Every writable that was ever created is settled one way or the other.
    for (const f of destFiles) {
      expect(f.writableCreated && !f.closed && !f.aborted).toBe(false);
    }
    // No in-flight source reads remain.
    expect(ctrl.track.active).toBe(0);
  });

  it("writes a large file in 16 MB chunks: byte total matches and multiple writes occur", async () => {
    // 40 MB virtual file (no real allocation in the source fake): the chunked
    // copy must slice it as 16 + 16 + 8 MB, i.e. at least 3 write() calls.
    const ctrl = makeCtrl();
    const root = makeSourceDir("library", {
      s1: { "big.fits": { virtualSize: 40 * MB } },
    }, ctrl);
    const dest = makeDestDir("staging");
    const onProgress = vi.fn();

    const result = await runBrowserCopy(root, dest, baseOpts([op("s1")], { onProgress }));

    expect(result.copied).toBe(1);
    const big = collectDestFiles(dest).find((f) => f.name === "big.fits")!;
    expect(big).toBeDefined();
    expect(big.writes).toBeGreaterThanOrEqual(3);
    const totalBytes = big.chunks.reduce((acc, c) => acc + c.length, 0);
    expect(totalBytes).toBe(40 * MB);
    expect(big.closed).toBe(true);
    expect(big.aborted).toBe(false);
    // Still one progress report for the whole file, not one per chunk, and it
    // carries the full byte size for rate computation.
    expect(onProgress).toHaveBeenCalledTimes(1);
    expect(onProgress).toHaveBeenCalledWith(1, 1, expect.any(String), 40 * MB);
  });

  it("copies a zero-byte file: destination created and closed with no writes", async () => {
    const ctrl = makeCtrl();
    const root = makeSourceDir("library", {
      s1: { "empty.fits": b(""), "tiny.fits": b("x") },
    }, ctrl);
    const dest = makeDestDir("staging");

    const result = await runBrowserCopy(root, dest, baseOpts([op("s1")]));

    expect(result.copied).toBe(2);
    const empty = collectDestFiles(dest).find((f) => f.name === "empty.fits")!;
    expect(empty).toBeDefined();
    expect(empty.writableCreated).toBe(true);
    expect(empty.closed).toBe(true);
    expect(empty.aborted).toBe(false);
    expect(empty.chunks.reduce((acc, c) => acc + c.length, 0)).toBe(0);
    expect(flattenDest(dest).get("s1/tiny.fits")).toBe("x");
  });
});
