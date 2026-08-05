import { describe, it, expect, vi } from "vitest";

import { scanForNames, moveMatches, type MoveScan } from "./frameListBrowserMove";

// --- Fake File System Access handles -----------------------------------------
//
// In-memory mutable directory tree mirroring wbppBrowserCopy.test.ts's harness,
// but writable: getFileHandle(create), removeEntry, and an optional
// FileSystemFileHandle.move() actually mutate the tree, so a move's effect can
// be asserted by inspecting the tree afterwards. Only the surface
// frameListBrowserMove touches is modelled: values(), getDirectoryHandle,
// getFileHandle, removeEntry, getFile().arrayBuffer(), createWritable(), and
// (when enabled) move(destDir, newName).

type Spec = { [name: string]: Spec | string };

interface Log {
  moveCalls: { name: string; target: string }[];
  removeCalls: string[];
  writableTargets: string[];
}

const emptyLog = (): Log => ({ moveCalls: [], removeCalls: [], writableTargets: [] });

interface TreeOpts {
  // When true, source file handles expose move() (the preferred path).
  withMove?: boolean;
  // Returning an Error makes that file's move()/read fail (a locked file).
  fail?: (name: string) => Error | undefined;
}

function concat(chunks: Uint8Array[]): Uint8Array {
  const total = chunks.reduce((acc, c) => acc + c.length, 0);
  const out = new Uint8Array(total);
  let off = 0;
  for (const c of chunks) {
    out.set(c, off);
    off += c.length;
  }
  return out;
}

function makeTree(spec: Spec, opts: TreeOpts = {}): { root: any; log: Log } {
  const log = emptyLog();

  function makeFile(name: string, content: string, parent: any): any {
    const f: any = {
      kind: "file",
      name,
      content,
      parent,
      async getFile() {
        return {
          size: f.content.length,
          arrayBuffer: async (): Promise<ArrayBuffer> => {
            const err = opts.fail?.(f.name);
            if (err) throw err;
            // Copy into a same-realm buffer (jsdom's TextEncoder realm issue).
            const enc = new TextEncoder().encode(f.content);
            const out = new Uint8Array(enc.length);
            out.set(enc);
            return out.buffer;
          },
        };
      },
      async createWritable() {
        log.writableTargets.push(f.name);
        const chunks: Uint8Array[] = [];
        return {
          async write(buf: ArrayBuffer) {
            chunks.push(new Uint8Array(buf));
          },
          async close() {
            f.content = new TextDecoder().decode(concat(chunks));
          },
          async abort() {
            f.aborted = true;
          },
        };
      },
    };
    if (opts.withMove) {
      f.move = async (destDir: any, newName?: string) => {
        const err = opts.fail?.(f.name);
        if (err) throw err;
        const target = newName ?? f.name;
        log.moveCalls.push({ name: f.name, target });
        f.parent.entries.delete(f.name);
        f.name = target;
        f.parent = destDir;
        destDir.entries.set(target, f);
      };
    }
    return f;
  }

  function makeDir(name: string, s: Spec): any {
    const entries = new Map<string, any>();
    const dir: any = {
      kind: "directory",
      name,
      entries,
      async *values() {
        for (const v of Array.from(entries.values())) yield v;
      },
      async getDirectoryHandle(n: string, o?: { create?: boolean }) {
        const e = entries.get(n);
        if (e?.kind === "directory") return e;
        if (e) throw new Error(`TypeMismatchError: ${n}`);
        if (!o?.create) throw new Error(`NotFoundError: ${n}`);
        const d = makeDir(n, {});
        entries.set(n, d);
        return d;
      },
      async getFileHandle(n: string, o?: { create?: boolean }) {
        const e = entries.get(n);
        if (e?.kind === "file") return e;
        if (e) throw new Error(`TypeMismatchError: ${n}`);
        if (!o?.create) throw new Error(`NotFoundError: ${n}`);
        const f = makeFile(n, "", dir);
        entries.set(n, f);
        return f;
      },
      async removeEntry(n: string) {
        if (!entries.has(n)) throw new Error(`NotFoundError: ${n}`);
        log.removeCalls.push(n);
        entries.delete(n);
      },
    };
    for (const [n, v] of Object.entries(s)) {
      entries.set(n, typeof v === "string" ? makeFile(n, v, dir) : makeDir(n, v));
    }
    return dir;
  }

  return { root: makeDir("root", spec), log };
}

// Recursively flattens files to relPath -> content for whole-tree assertions.
function flatten(dir: any, prefix = ""): Map<string, string> {
  const out = new Map<string, string>();
  for (const [n, e] of dir.entries as Map<string, any>) {
    const rel = prefix ? `${prefix}/${n}` : n;
    if (e.kind === "file") out.set(rel, e.content);
    else for (const [p, c] of flatten(e, rel)) out.set(p, c);
  }
  return out;
}

// Standard fixture: nested filter folders, a collision (a.fits twice), a name
// already sitting in _rejected (x.fits, so the incoming one must be suffixed),
// and a pre-existing _rejected subtree the scan must skip entirely.
const SPEC: Spec = {
  "2026-01-01": {
    Ha: { "a.fits": "A1", "x.fits": "X-src" },
    Oiii: { "a.fits": "A2", "b.fits": "B" },
  },
  _rejected: { "b.fits": "old-b", "x.fits": "old-x" },
};

const NAMES = ["a.fits", "b.fits", "x.fits", "ghost.fits"];

describe("scanForNames", () => {
  it("finds every hit outside _rejected and reports missing and collisions", async () => {
    const { root } = makeTree(SPEC);

    const scan = await scanForNames(root, NAMES);

    expect(scan.root).toBe(root);
    expect(scan.matches.map((m) => m.relPath).sort()).toEqual([
      "2026-01-01/Ha/a.fits",
      "2026-01-01/Ha/x.fits",
      "2026-01-01/Oiii/a.fits",
      "2026-01-01/Oiii/b.fits",
    ]);
    for (const m of scan.matches) {
      expect(m.parent).toBeTruthy();
      expect(m.relPath.endsWith(m.name)).toBe(true);
      // The _rejected copies of b.fits and x.fits must never be matched.
      expect(m.relPath.startsWith("_rejected")).toBe(false);
    }
    expect(scan.missing).toEqual(["ghost.fits"]);
    expect(scan.collisions).toEqual(["a.fits"]);
  });

  it("skips _rejected folders at any depth and dedupes repeated input names", async () => {
    const { root } = makeTree({
      s1: { _rejected: { "a.fits": "buried" }, "a.fits": "live" },
    });

    const scan = await scanForNames(root, ["a.fits", "a.fits"]);

    expect(scan.matches.map((m) => m.relPath)).toEqual(["s1/a.fits"]);
    expect(scan.collisions).toEqual([]);
    expect(scan.missing).toEqual([]);
  });
});

describe("moveMatches", () => {
  it("prefers move() when the handle exposes it: no copies, no removeEntry, suffixed collisions", async () => {
    const { root, log } = makeTree(SPEC, { withMove: true });
    const scan = await scanForNames(root, NAMES);
    const onProgress = vi.fn();

    const result = await moveMatches(scan, onProgress, new AbortController().signal);

    expect(result.moved).toBe(4);
    expect(result.failed).toEqual([]);
    expect(log.moveCalls.length).toBe(4);
    expect(log.writableTargets).toEqual([]);
    expect(log.removeCalls).toEqual([]);

    const flat = flatten(root);
    // Sources are gone.
    expect(flat.has("2026-01-01/Ha/a.fits")).toBe(false);
    expect(flat.has("2026-01-01/Ha/x.fits")).toBe(false);
    expect(flat.has("2026-01-01/Oiii/a.fits")).toBe(false);
    expect(flat.has("2026-01-01/Oiii/b.fits")).toBe(false);
    // First a.fits keeps its name; the collision twin gets _1. x.fits and
    // b.fits collide with files already sitting in _rejected, so they are
    // suffixed too and the pre-existing files stay untouched.
    expect(flat.get("_rejected/a.fits")).toBe("A1");
    expect(flat.get("_rejected/a_1.fits")).toBe("A2");
    expect(flat.get("_rejected/x.fits")).toBe("old-x");
    expect(flat.get("_rejected/x_1.fits")).toBe("X-src");
    expect(flat.get("_rejected/b.fits")).toBe("old-b");
    expect(flat.get("_rejected/b_1.fits")).toBe("B");

    // One progress report per file with a stable total.
    expect(onProgress.mock.calls).toEqual([
      [1, 4],
      [2, 4],
      [3, 4],
      [4, 4],
    ]);
  });

  it("falls back to byte copy + removeEntry when the handle has no move()", async () => {
    const { root, log } = makeTree(SPEC, { withMove: false });
    const scan = await scanForNames(root, NAMES);

    const result = await moveMatches(scan, vi.fn(), new AbortController().signal);

    expect(result.moved).toBe(4);
    expect(result.failed).toEqual([]);
    expect(log.moveCalls).toEqual([]);
    expect(log.writableTargets.length).toBe(4);
    expect(log.removeCalls.sort()).toEqual(["a.fits", "a.fits", "b.fits", "x.fits"]);

    const flat = flatten(root);
    expect(flat.has("2026-01-01/Ha/a.fits")).toBe(false);
    expect(flat.get("_rejected/a.fits")).toBe("A1");
    expect(flat.get("_rejected/a_1.fits")).toBe("A2");
    expect(flat.get("_rejected/x_1.fits")).toBe("X-src");
    expect(flat.get("_rejected/b_1.fits")).toBe("B");
    expect(flat.get("_rejected/x.fits")).toBe("old-x");
  });

  it("stops between files when the signal aborts and reports only what moved", async () => {
    const { root } = makeTree(SPEC, { withMove: true });
    const scan = await scanForNames(root, NAMES);
    const controller = new AbortController();
    const onProgress = vi.fn((done: number) => {
      if (done === 1) controller.abort();
    });

    const result = await moveMatches(scan, onProgress, controller.signal);

    expect(result.moved).toBe(1);
    expect(result.failed).toEqual([]);
    expect(onProgress).toHaveBeenCalledTimes(1);
    // Three of the four matches never moved.
    const flat = flatten(root);
    const remaining = scan.matches.filter((m) => flat.has(m.relPath));
    expect(remaining.length).toBe(3);
  });

  it("reports per-file failures without throwing and keeps moving the rest", async () => {
    const locked = new Error("locked");
    const { root } = makeTree(SPEC, {
      withMove: true,
      fail: (name) => (name === "b.fits" ? locked : undefined),
    });
    const scan = await scanForNames(root, NAMES);

    const result = await moveMatches(scan, vi.fn(), new AbortController().signal);

    expect(result.moved).toBe(3);
    expect(result.failed).toEqual([
      { relPath: "2026-01-01/Oiii/b.fits", message: "locked" },
    ]);
    const flat = flatten(root);
    // The failed file stays put; everything else moved.
    expect(flat.get("2026-01-01/Oiii/b.fits")).toBe("B");
    expect(flat.get("_rejected/a.fits")).toBe("A1");
    expect(flat.get("_rejected/a_1.fits")).toBe("A2");
    expect(flat.get("_rejected/x_1.fits")).toBe("X-src");
  });

  it("failed fallback reads leave the source intact and are reported", async () => {
    const boom = new Error("read failed");
    const { root, log } = makeTree(SPEC, {
      withMove: false,
      fail: (name) => (name === "b.fits" ? boom : undefined),
    });
    const scan = await scanForNames(root, NAMES);

    const result = await moveMatches(scan, vi.fn(), new AbortController().signal);

    expect(result.moved).toBe(3);
    expect(result.failed).toEqual([
      { relPath: "2026-01-01/Oiii/b.fits", message: "read failed" },
    ]);
    // The failing file was never removed from its source folder.
    expect(log.removeCalls).not.toContain("b.fits");
    expect(flatten(root).get("2026-01-01/Oiii/b.fits")).toBe("B");
  });
});

// Type-only sanity: MoveScan is exported and structurally what the modal expects.
const _typeCheck = (s: MoveScan): number => s.matches.length + s.missing.length + s.collisions.length;
void _typeCheck;
