// Path helpers shared by the WBPP export modal and its level editor.
//
// Both render library paths produced on the user's PixInsight machine, so the
// separator is whatever that machine uses.
//
// The separator has ONE source of truth: the modal's `effectiveOs()`, which
// prefers the user's persisted `wbpp_default_os` and only falls back to guessing
// from the root string via `detectOs` below. Everything that renders a path takes
// the resolved separator as an argument (WbppLevelEditor's `separator` prop,
// `joinRoot`'s `sep`) rather than re-deriving it.
//
// There was a `separatorFor(root)` here that guessed the separator straight from
// the root's shape. It is gone deliberately: it answered the same question from a
// worse input, so a pinned OS of "windows" with a root like `/mnt/astro` made it
// disagree with the generated script. Do not reintroduce it -- a second guess
// reachable from a shared module is how that drift gets back in. Resolve the OS
// once, then pass the separator down.

export type PathOs = "windows" | "posix";

/**
 * Windows iff the root carries a backslash (drive-letter roots like `Z:\Astro`
 * and UNC roots both do). Preserves the modal's original regex behaviour.
 *
 * The fallback for an unset preference only. Prefer the persisted choice when
 * there is one; this cannot see it.
 */
export function detectOs(root: string): PathOs {
  return /^[A-Za-z]:\\|\\/.test(root) ? "windows" : "posix";
}

/** Last path segment, tolerant of either separator. */
export function lastSegment(path: string): string {
  const parts = path.split(/[/\\]/).filter((p) => p.length > 0);
  return parts.length ? parts[parts.length - 1] : path;
}

/**
 * Everything before the last segment, separator included, so
 * `parentContext(p) + lastSegment(p)` reconstructs `p` for any path with a
 * parent. Empty string when the path is a bare segment. Lets a row show the
 * leaf at full strength and ellipsize only the context in front of it.
 */
export function parentContext(path: string): string {
  const leaf = lastSegment(path);
  if (leaf === path) return "";
  const cut = path.lastIndexOf(leaf);
  return cut <= 0 ? "" : path.slice(0, cut);
}

/** Append `sep` to `root` unless it already ends in a separator. */
export function joinRoot(root: string, sep: string): string {
  return root.endsWith("/") || root.endsWith("\\") ? root : root + sep;
}
