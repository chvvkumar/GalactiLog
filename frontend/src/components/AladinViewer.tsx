import { Component, onMount, onCleanup, createSignal } from "solid-js";

declare global {
  interface Window {
    A: any;
  }
}

interface AladinViewerProps {
  ra: number;
  dec: number;
  fov?: number;
}

const SURVEYS = [
  { label: "DSS2 Color", id: "P/DSS2/color" },
  { label: "DSS2 Red", id: "P/DSS2/red" },
  { label: "2MASS Color", id: "P/2MASS/color" },
  { label: "PanSTARRS DR1", id: "P/PanSTARRS/DR1/color-z-zg-g" },
  { label: "AllWISE Color", id: "P/allWISE/color" },
];

const AladinViewer: Component<AladinViewerProps> = (props) => {
  let containerRef: HTMLDivElement | undefined;
  let aladinInstance: any;
  const [survey, setSurvey] = createSignal(SURVEYS[0].id);
  const [loading, setLoading] = createSignal(true);

  const initAladin = () => {
    if (!containerRef || !window.A) return;

    const fov = props.fov ?? 0.5;
    aladinInstance = window.A.aladin(containerRef, {
      survey: survey(),
      fov,
      target: `${props.ra} ${props.dec}`,
      showReticle: true,
      showZoomControl: true,
      showFullscreenControl: true,
      showLayersControl: false,
      showGotoControl: false,
    });
    setLoading(false);
  };

  onMount(() => {
    if (window.A) {
      initAladin();
    } else {
      const check = setInterval(() => {
        if (window.A) {
          clearInterval(check);
          initAladin();
        }
      }, 200);
      setTimeout(() => clearInterval(check), 10000);
    }
  });

  onCleanup(() => {
    aladinInstance = undefined;
  });

  const changeSurvey = (newSurvey: string) => {
    setSurvey(newSurvey);
    if (aladinInstance) {
      aladinInstance.setImageSurvey(newSurvey);
    }
  };

  return (
    <div class="relative">
      <div class="flex items-center gap-2 mb-2">
        <select
          class="text-xs bg-theme-surface border border-theme-border rounded px-2 py-1 text-theme-text-secondary"
          value={survey()}
          onChange={(e) => changeSurvey(e.currentTarget.value)}
        >
          {SURVEYS.map((s) => (
            <option value={s.id}>{s.label}</option>
          ))}
        </select>
      </div>
      <div
        ref={containerRef}
        class="w-full h-64 rounded-[var(--radius-sm)] overflow-hidden border border-theme-border"
        style={{ "min-height": "256px" }}
      />
      {loading() && (
        <div class="absolute inset-0 flex items-center justify-center bg-theme-surface/80 rounded-[var(--radius-sm)]">
          <span class="text-xs text-theme-muted">Loading sky viewer...</span>
        </div>
      )}
    </div>
  );
};

export default AladinViewer;
