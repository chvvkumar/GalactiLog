export function formatIntegration(seconds: number): string {
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  return `${h.toString().padStart(2, "0")}h ${m.toString().padStart(2, "0")}m`;
}

const WIDTH_CLASSES: Record<string, string> = {
  "full": "",
  "wide": "max-w-[1792px] mx-auto",
  "standard": "max-w-screen-2xl mx-auto",
  "compact": "max-w-7xl mx-auto",
};

export function contentWidthClass(width: string): string {
  return WIDTH_CLASSES[width] ?? "";
}
