import { Component, onCleanup } from "solid-js";
import { sidebarWidth, setSidebarWidth, setResizing, resetSidebarWidth } from "./sidebarLayout";

const SidebarResizeHandle: Component = () => {
  let startX = 0;
  let startWidth = 0;

  const onPointerMove = (e: PointerEvent) => {
    const dx = e.clientX - startX;
    setSidebarWidth(startWidth + dx);
  };

  const endDrag = () => {
    setResizing(false);
    window.removeEventListener("pointermove", onPointerMove);
    window.removeEventListener("pointerup", onPointerUp);
    window.removeEventListener("pointercancel", onPointerUp);
  };

  const onPointerUp = (e: PointerEvent) => {
    (e.target as HTMLElement).releasePointerCapture?.(e.pointerId);
    endDrag();
  };

  onCleanup(endDrag);

  const onPointerDown = (e: PointerEvent) => {
    e.preventDefault();
    startX = e.clientX;
    startWidth = sidebarWidth();
    setResizing(true);
    (e.target as HTMLElement).setPointerCapture?.(e.pointerId);
    window.addEventListener("pointermove", onPointerMove);
    window.addEventListener("pointerup", onPointerUp);
    window.addEventListener("pointercancel", onPointerUp);
  };

  return (
    <div
      role="separator"
      aria-orientation="vertical"
      aria-label="Resize sidebar"
      onPointerDown={onPointerDown}
      onDblClick={() => resetSidebarWidth()}
      class="absolute top-0 right-0 h-full w-1 hover:w-1.5 cursor-col-resize bg-transparent hover:bg-theme-border-em transition-[width,background-color] duration-150 z-10"
      style={{ "touch-action": "none" }}
    />
  );
};

export default SidebarResizeHandle;
