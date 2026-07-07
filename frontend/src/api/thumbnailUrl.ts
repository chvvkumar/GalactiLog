// Shared URL-builder for thumbnail images served from /thumbnails/<filename>.
// Not an HTTP call through apiClient -- this only derives a path string from
// a stored file path (ported verbatim from the old `client.ts:459`
// `thumbnailUrl`). Kept in its own module (rather than inlined in
// ReferenceThumbnail.tsx) so other components that build the same URL
// (KonvaMosaicArranger.tsx, migrated in a later slice) can import this
// implementation instead of duplicating it or reaching back into the old
// `api` object.
export function thumbnailUrl(path: string): string {
  const filename = path.split("/").pop();
  return `/thumbnails/${filename}`;
}
