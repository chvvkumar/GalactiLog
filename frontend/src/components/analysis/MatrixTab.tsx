import { Component, createMemo, createResource, For } from "solid-js";
import { api } from "../../api/client";
import type { SharedFilters } from "../../pages/AnalysisPage";

const X_LABELS: Record<string, string> = {
  humidity: "Humid.", wind_speed: "Wind", ambient_temp: "Temp",
  dew_point: "Dew Pt", pressure: "Press.", cloud_cover: "Cloud",
  sky_quality: "SQM", focuser_temp: "Focus T", airmass: "Airm.", sensor_temp: "Sensor T",
};

const Y_LABELS: Record<string, string> = {
  hfr: "HFR", fwhm: "FWHM", eccentricity: "Ecc.",
  guiding_rms: "Guide", guiding_rms_ra: "Guide RA", guiding_rms_dec: "Guide DEC",
  detected_stars: "Stars", adu_mean: "ADU \u03bc", adu_median: "ADU med", adu_stdev: "ADU \u03c3",
};

function rToColor(r: number | null): string {
  if (r === null) return "rgba(80, 80, 80, 0.3)";
  const abs = Math.min(Math.abs(r), 1);
  const alpha = 0.15 + abs * 0.65;
  if (r < 0) return `rgba(80, 140, 255, ${alpha})`;
  return `rgba(255, 100, 80, ${alpha})`;
}

interface Props {
  filters: SharedFilters;
}

const MatrixTab: Component<Props> = (props) => {
  const dataKey = () =>
    `matrix-${props.filters.telescope}-${props.filters.camera}-${props.filters.filterUsed}-${props.filters.dateFrom}-${props.filters.dateTo}`;

  const [data] = createResource(dataKey, () =>
    api.getMatrix({
      telescope: props.filters.telescope,
      camera: props.filters.camera,
      filter_used: props.filters.filterUsed,
      date_from: props.filters.dateFrom,
      date_to: props.filters.dateTo,
    })
  );

  const cellMap = createMemo(() => {
    const d = data();
    type Cell = NonNullable<typeof d>["cells"][number];
    if (!d) return new Map<string, Cell>();
    const map = new Map<string, Cell>();
    for (const c of d.cells) {
      map.set(`${c.x_metric}:${c.y_metric}`, c);
    }
    return map;
  });

  const getCell = (xm: string, ym: string) => {
    return cellMap().get(`${xm}:${ym}`) ?? null;
  };

  return (
    <div class="bg-theme-surface border border-theme-border rounded-[var(--radius-md)] shadow-[var(--shadow-sm)] p-4">
      <h3 class="text-base font-medium text-theme-text-primary mb-3">Correlation Matrix</h3>
      <p class="text-xs text-theme-text-tertiary mb-3">Pearson r for all metric pairs. Click a cell to explore in the Correlation tab.</p>

      {data.loading && !data() && (
        <div class="text-sm text-theme-text-secondary py-8 text-center">Computing correlations...</div>
      )}

      {data() && (
        <div class="overflow-x-auto">
          <table class="text-xs border-collapse">
            <thead>
              <tr>
                <th class="p-1"></th>
                <For each={data()!.x_metrics}>
                  {(xm) => (
                    <th class="p-1.5 text-theme-text-secondary font-normal whitespace-nowrap" style={{ "writing-mode": "vertical-lr", transform: "rotate(180deg)" }}>
                      {X_LABELS[xm] || xm}
                    </th>
                  )}
                </For>
              </tr>
            </thead>
            <tbody>
              <For each={data()!.y_metrics}>
                {(ym) => (
                  <tr>
                    <td class="p-1.5 text-theme-text-secondary whitespace-nowrap text-right pr-2">{Y_LABELS[ym] || ym}</td>
                    <For each={data()!.x_metrics}>
                      {(xm) => {
                        const cell = () => getCell(xm, ym);
                        return (
                          <td
                            class="p-1.5 text-center cursor-pointer hover:ring-1 hover:ring-theme-accent transition-shadow rounded-sm"
                            style={{ "background-color": rToColor(cell()?.pearson_r ?? null), "min-width": "42px" }}
                            title={cell()?.pearson_r !== null
                              ? `r=${cell()!.pearson_r!.toFixed(3)} (N=${cell()!.n_points})`
                              : `Insufficient data (N=${cell()?.n_points || 0})`}
                            onClick={() => {
                              if (cell()?.pearson_r !== null) {
                                window.dispatchEvent(new CustomEvent("analysis-navigate", { detail: { tab: "correlation", x: xm, y: ym } }));
                              }
                            }}
                          >
                            <span class="text-theme-text-primary text-tiny">
                              {cell()?.pearson_r !== null ? cell()!.pearson_r!.toFixed(2) : "\u2014"}
                            </span>
                          </td>
                        );
                      }}
                    </For>
                  </tr>
                )}
              </For>
            </tbody>
          </table>

          {/* Legend */}
          <div class="flex items-center gap-2 mt-3 text-xs text-theme-text-secondary">
            <span>Negative</span>
            <div class="flex h-3">
              {[-0.8, -0.4, 0, 0.4, 0.8].map((r) => (
                <div style={{ "background-color": rToColor(r), width: "24px" }} />
              ))}
            </div>
            <span>Positive</span>
            <div class="ml-3 w-6 h-3 rounded-sm" style={{ "background-color": rToColor(null) }} />
            <span>No data</span>
          </div>
        </div>
      )}
    </div>
  );
};

export default MatrixTab;
