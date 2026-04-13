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

  const loadAladinLibrary = (): Promise<void> => {
    return new Promise((resolve, reject) => {
      // Load CSS if not already present
      if (!document.querySelector('link[href*="aladin.min.css"]')) {
        const link = document.createElement("link");
        link.rel = "stylesheet";
        link.href =
          "https://aladin.cds.unistra.fr/AladinLite/api/v3/latest/aladin.min.css";
        document.head.appendChild(link);
      }

      // Load JS if not already present
      if (window.A) {
        resolve();
        return;
      }

      if (document.querySelector('script[src*="aladin.js"]')) {
        // Script tag exists but hasn't finished loading yet
        const check = setInterval(() => {
          if (window.A) {
            clearInterval(check);
            resolve();
          }
        }, 200);
        setTimeout(() => {
          clearInterval(check);
          reject(new Error("Aladin script load timeout"));
        }, 15000);
        return;
      }

      const script = document.createElement("script");
      script.type = "module";
      script.src =
        "https://aladin.cds.unistra.fr/AladinLite/api/v3/latest/aladin.js";
      script.charset = "utf-8";
      script.onload = () => {
        // window.A may not be available immediately after script load
        const check = setInterval(() => {
          if (window.A) {
            clearInterval(check);
            resolve();
          }
        }, 100);
        setTimeout(() => {
          clearInterval(check);
          reject(new Error("Aladin init timeout"));
        }, 15000);
      };
      script.onerror = () => reject(new Error("Failed to load Aladin script"));
      document.head.appendChild(script);
    });
  };

  onMount(() => {
    loadAladinLibrary()
      .then(() => initAladin())
      .catch((err) => {
        console.error("Aladin failed to load:", err);
        setLoading(false);
      });
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
    <div class="relative flex flex-col flex-1">
      <div class="flex items-center gap-2 mb-2 flex-shrink-0">
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
        class="w-full h-full rounded-[var(--radius-sm)] overflow-hidden border border-theme-border"
        style={{ "min-height": "300px" }}
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
