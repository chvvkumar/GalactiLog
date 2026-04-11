import { createSignal } from "solid-js";

export const MIN_WIDTH = 220;
export const MAX_WIDTH = 480;
export const DEFAULT_WIDTH = 288;
export const RAIL_WIDTH = 48;

const WIDTH_KEY = "galactilog.sidebar.width";
const COLLAPSED_KEY = "galactilog.sidebar.collapsed";

function clamp(n: number): number {
  if (Number.isNaN(n)) return DEFAULT_WIDTH;
  if (n < MIN_WIDTH) return MIN_WIDTH;
  if (n > MAX_WIDTH) return MAX_WIDTH;
  return n;
}

function loadWidth(): number {
  try {
    const raw = localStorage.getItem(WIDTH_KEY);
    if (raw == null) return DEFAULT_WIDTH;
    return clamp(parseInt(raw, 10));
  } catch {
    return DEFAULT_WIDTH;
  }
}

function loadCollapsed(): boolean {
  try {
    return localStorage.getItem(COLLAPSED_KEY) === "1";
  } catch {
    return false;
  }
}

const [widthSig, setWidthSig] = createSignal<number>(loadWidth());
const [collapsedSig, setCollapsedSig] = createSignal<boolean>(loadCollapsed());
const [resizingSig, setResizingSig] = createSignal<boolean>(false);

// Bus: increments whenever a section-expand is requested.
// Consumers createEffect on [pendingExpandId, expandTick] to react even on repeats.
const [pendingExpandId, setPendingExpandId] = createSignal<string | null>(null);
const [expandTick, setExpandTick] = createSignal<number>(0);

export const sidebarWidth = widthSig;
export const sidebarCollapsed = collapsedSig;
export const resizing = resizingSig;
export const expandRequestId = pendingExpandId;
export const expandRequestTick = expandTick;

export function setSidebarWidth(px: number): void {
  const next = clamp(px);
  setWidthSig(next);
  try {
    localStorage.setItem(WIDTH_KEY, String(next));
  } catch { /* ignore */ }
}

export function resetSidebarWidth(): void {
  setSidebarWidth(DEFAULT_WIDTH);
}

export function setSidebarCollapsed(v: boolean): void {
  setCollapsedSig(v);
  try {
    localStorage.setItem(COLLAPSED_KEY, v ? "1" : "0");
  } catch { /* ignore */ }
}

export function toggleSidebarCollapsed(): void {
  setSidebarCollapsed(!collapsedSig());
}

export function setResizing(v: boolean): void {
  setResizingSig(v);
}

export function requestExpandSection(id: string): void {
  setPendingExpandId(id);
  setExpandTick(expandTick() + 1);
}
