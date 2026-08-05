// Browser-native "move to _rejected" for the Copy Frame List modal, built on
// the File System Access API (support gate and picker live in wbppBrowserCopy).
//
// The user picks a base folder; scanForNames walks it for the selected bare
// file names (the same identity the clipboard formats use, so the same caveat
// applies: one name can match several paths and every hit is reported), then
// moveMatches relocates every hit into a _rejected subfolder directly under
// the picked root. Any directory named _rejected is skipped during the scan,
// so re-running never re-matches already rejected files.
//
// Handles are typed loosely for the same reason as wbppBrowserCopy: lib.dom
// does not declare the async-iterator or move() surface on all TS versions.

type DirHandle = any;
type FileHandle = any;

const REJECTED = "_rejected";

export interface MoveMatch {
  /** Bare file name searched for. */
  name: string;
  /** Path relative to the picked root, "/"-separated. */
  relPath: string;
  parent: FileSystemDirectoryHandle;
}

export interface MoveScan {
  root: FileSystemDirectoryHandle;
  /** Every hit outside any _rejected folder, in walk order. */
  matches: MoveMatch[];
  /** Names with zero hits. */
  missing: string[];
  /** Names with more than one hit (all hits still appear in matches). */
  collisions: string[];
}

export interface MoveResult {
  moved: number;
  failed: { relPath: string; message: string }[];
}

/**
 * Walk `root` recursively, skipping every directory named _rejected at any
 * depth, and collect each file whose bare name is in `names` (duplicated
 * input names are deduped).
 */
export async function scanForNames(
  root: FileSystemDirectoryHandle,
  names: string[],
): Promise<MoveScan> {
  const wanted = new Set(names);
  const hitCounts = new Map<string, number>();
  const matches: MoveMatch[] = [];

  const walk = async (dir: DirHandle, rel: string): Promise<void> => {
    for await (const entry of dir.values()) {
      if (entry.kind === "directory") {
        if (entry.name === REJECTED) continue;
        await walk(entry, rel ? `${rel}/${entry.name}` : entry.name);
      } else if (wanted.has(entry.name)) {
        hitCounts.set(entry.name, (hitCounts.get(entry.name) ?? 0) + 1);
        matches.push({
          name: entry.name,
          relPath: rel ? `${rel}/${entry.name}` : entry.name,
          parent: dir,
        });
      }
    }
  };
  await walk(root as DirHandle, "");

  const missing: string[] = [];
  const collisions: string[] = [];
  const seen = new Set<string>();
  for (const n of names) {
    if (seen.has(n)) continue;
    seen.add(n);
    const count = hitCounts.get(n) ?? 0;
    if (count === 0) missing.push(n);
    else if (count > 1) collisions.push(n);
  }

  return { root, matches, missing, collisions };
}

function splitExtension(name: string): [stem: string, ext: string] {
  const dot = name.lastIndexOf(".");
  // dot <= 0 covers extensionless names and dotfiles like ".hidden".
  if (dot <= 0) return [name, ""];
  return [name.slice(0, dot), name.slice(dot)];
}

/**
 * First free file name in `dest`: the name itself, else stem_1.ext, stem_2.ext
 * and so on. Existence is probed with a non-creating getFileHandle, so files
 * moved earlier in the same run count as taken too.
 */
async function freeName(dest: DirHandle, name: string): Promise<string> {
  const taken = async (candidate: string): Promise<boolean> => {
    try {
      await dest.getFileHandle(candidate, { create: false });
      return true;
    } catch {
      return false;
    }
  };
  if (!(await taken(name))) return name;
  const [stem, ext] = splitExtension(name);
  for (let i = 1; ; i += 1) {
    const candidate = `${stem}_${i}${ext}`;
    if (!(await taken(candidate))) return candidate;
  }
}

/**
 * Move every match into <root>/_rejected. Prefers FileSystemFileHandle.move()
 * (feature-detected: lib.dom does not declare it); falls back to a byte copy
 * plus parent.removeEntry. Duplicate names landing in _rejected are suffixed
 * _1/_2 before the extension. Per-file errors are collected into the result,
 * never thrown. The signal is checked between files: aborting stops the run
 * and resolves with what moved so far.
 */
export async function moveMatches(
  scan: MoveScan,
  onProgress: (done: number, total: number) => void,
  signal: AbortSignal,
): Promise<MoveResult> {
  const root = scan.root as DirHandle;
  const dest = await root.getDirectoryHandle(REJECTED, { create: true });
  const total = scan.matches.length;
  let done = 0;
  let moved = 0;
  const failed: MoveResult["failed"] = [];

  for (const match of scan.matches) {
    if (signal.aborted) break;
    try {
      const fh: FileHandle = await (match.parent as DirHandle).getFileHandle(match.name, {
        create: false,
      });
      const target = await freeName(dest, match.name);
      const mover = (fh as { move?: (dir: DirHandle, name?: string) => Promise<void> }).move;
      if (typeof mover === "function") {
        await mover.call(fh, dest, target);
      } else {
        // Fallback: copy the bytes into _rejected, then remove the source.
        // The source is only removed after a fully closed write, so a failed
        // copy never loses the file.
        const file = await fh.getFile();
        const out = await dest.getFileHandle(target, { create: true });
        const writable = await out.createWritable();
        try {
          await writable.write(await file.arrayBuffer());
          await writable.close();
        } catch (e) {
          try {
            await writable.abort();
          } catch {
            // Best-effort cleanup; surface the original error.
          }
          throw e;
        }
        await (match.parent as DirHandle).removeEntry(match.name);
      }
      moved += 1;
    } catch (e) {
      failed.push({
        relPath: match.relPath,
        message: e instanceof Error ? e.message : String(e),
      });
    }
    done += 1;
    onProgress(done, total);
  }

  return { moved, failed };
}
