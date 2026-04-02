import { Component, createSignal, createResource } from "solid-js";
import { api } from "../api/client";
import { useStats } from "../store/stats";
import CorrelationChart from "../components/analysis/CorrelationChart";

const X_OPTIONS = [
  { value: "humidity", label: "Humidity" },
  { value: "wind_speed", label: "Wind Speed" },
  { value: "ambient_temp", label: "Ambient Temp" },
  { value: "dew_point", label: "Dew Point" },
  { value: "pressure", label: "Pressure" },
  { value: "cloud_cover", label: "Cloud Cover" },
  { value: "sky_quality", label: "Sky Quality" },
  { value: "focuser_temp", label: "Focuser Temp" },
  { value: "airmass", label: "Airmass" },
  { value: "sensor_temp", label: "Sensor Temp" },
];

const Y_OPTIONS = [
  { value: "hfr", label: "HFR" },
  { value: "fwhm", label: "FWHM" },
  { value: "eccentricity", label: "Eccentricity" },
  { value: "guiding_rms", label: "Guiding RMS" },
  { value: "guiding_rms_ra", label: "Guiding RA RMS" },
  { value: "guiding_rms_dec", label: "Guiding DEC RMS" },
  { value: "detected_stars", label: "Detected Stars" },
  { value: "adu_mean", label: "ADU Mean" },
  { value: "adu_median", label: "ADU Median" },
  { value: "adu_stdev", label: "ADU StDev" },
];

const AnalysisPage: Component = () => {
  const { stats } = useStats();
  const [telescope, setTelescope] = createSignal<string | undefined>(undefined);
  const [camera, setCamera] = createSignal<string | undefined>(undefined);
  const [granularity, setGranularity] = createSignal<"frame" | "session">("frame");
  const [customX, setCustomX] = createSignal("humidity");
  const [customY, setCustomY] = createSignal("hfr");

  const fetchChart = (x: string, y: string) => {
    const tel = telescope();
    const cam = camera();
    const gran = granularity();
    return api.getCorrelation({
      x_metric: x,
      y_metric: y,
      telescope: tel,
      camera: cam,
      granularity: gran,
    });
  };

  const chartKey = () => `${telescope()}-${camera()}-${granularity()}-${customX()}-${customY()}`;
  const [customData] = createResource(chartKey, () =>
    fetchChart(customX(), customY())
  );

  const combos = () => {
    const s = stats();
    if (!s) return [];
    return s.equipment_performance.map((c) => ({
      telescope: c.telescope,
      camera: c.camera,
      label: `${c.telescope} + ${c.camera}`,
      grouped: c.grouped,
    }));
  };

  const equipmentValue = () => {
    const tel = telescope();
    const cam = camera();
    if (!tel && !cam) return "";
    return `${tel}|||${cam}`;
  };

  const selectClass = "text-xs bg-theme-elevated border border-theme-border rounded px-2 py-1 text-theme-text-primary";
  const toggleClass = (active: boolean) =>
    `text-xs px-2.5 py-1 rounded-[var(--radius-sm)] transition-colors ${
      active
        ? "bg-theme-elevated text-theme-text-primary font-medium"
        : "text-theme-text-secondary hover:text-theme-text-primary"
    }`;

  return (
    <div class="p-4 space-y-4 max-w-7xl mx-auto">
      {/* Controls */}
      <div class="flex flex-wrap items-center gap-3">
        <select
          class={selectClass}
          value={equipmentValue()}
          onChange={(e) => {
            const val = e.currentTarget.value;
            if (!val) {
              setTelescope(undefined);
              setCamera(undefined);
            } else {
              const [t, c] = val.split("|||");
              setTelescope(t);
              setCamera(c);
            }
          }}
        >
          <option value="">All equipment</option>
          {combos().map((c) => (
            <option value={`${c.telescope}|||${c.camera}`}>{c.label}{c.grouped ? " \u29C9" : ""}</option>
          ))}
        </select>

        <div class="flex items-center gap-1">
          <button class={toggleClass(granularity() === "frame")} onClick={() => setGranularity("frame")}>
            Per Frame
          </button>
          <button class={toggleClass(granularity() === "session")} onClick={() => setGranularity("session")}>
            Per Session
          </button>
        </div>
      </div>

      {/* Correlation explorer */}
      <div class="bg-theme-surface border border-theme-border rounded-[var(--radius-md)] shadow-[var(--shadow-sm)] p-4">
        <h3 class="text-sm font-medium text-theme-text-primary mb-3">Correlation Explorer</h3>
        <div class="flex flex-wrap items-center gap-3 mb-4">
          <label class="text-xs text-theme-text-secondary">X Axis:</label>
          <select class={selectClass} value={customX()} onChange={(e) => setCustomX(e.currentTarget.value)}>
            {X_OPTIONS.map((o) => <option value={o.value}>{o.label}</option>)}
          </select>
          <label class="text-xs text-theme-text-secondary">Y Axis:</label>
          <select class={selectClass} value={customY()} onChange={(e) => setCustomY(e.currentTarget.value)}>
            {Y_OPTIONS.map((o) => <option value={o.value}>{o.label}</option>)}
          </select>
        </div>
        <div style={{ height: "400px" }} class="relative">
          <CorrelationChart data={customData()} loading={customData.loading} />
        </div>
      </div>
    </div>
  );
};

export default AnalysisPage;
