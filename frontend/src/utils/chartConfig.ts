export interface MetricDefinition {
  key: string;
  label: string;
  colorVar: string;
  yAxisId: "left" | "right";
  frameField: string;
  overviewField: string;
  decimals: number;
  unit?: string;
}

export const METRIC_DEFINITIONS: MetricDefinition[] = [
  { key: "hfr", label: "HFR", colorVar: "--color-metric-hfr", yAxisId: "left", frameField: "median_hfr", overviewField: "median_hfr", decimals: 2 },
  { key: "eccentricity", label: "Ecc", colorVar: "--color-metric-eccentricity", yAxisId: "left", frameField: "eccentricity", overviewField: "median_eccentricity", decimals: 2 },
  { key: "fwhm", label: "FWHM", colorVar: "--color-metric-fwhm", yAxisId: "right", frameField: "fwhm", overviewField: "median_fwhm", decimals: 1 },
  { key: "guiding_rms", label: "Guide", colorVar: "--color-metric-guiding", yAxisId: "left", frameField: "guiding_rms_arcsec", overviewField: "median_guiding_rms_arcsec", decimals: 2, unit: '"' },
  { key: "detected_stars", label: "Stars", colorVar: "--color-metric-stars", yAxisId: "right", frameField: "detected_stars", overviewField: "median_detected_stars", decimals: 0 },
  { key: "sensor_temp", label: "Temp", colorVar: "--color-metric-temp", yAxisId: "right", frameField: "sensor_temp", overviewField: "", decimals: 0, unit: "°C" },
  { key: "ambient_temp", label: "Ambient", colorVar: "--color-metric-temp", yAxisId: "right", frameField: "ambient_temp", overviewField: "", decimals: 1, unit: "°C" },
  { key: "humidity", label: "Humidity", colorVar: "--color-metric-temp", yAxisId: "right", frameField: "humidity", overviewField: "", decimals: 0, unit: "%" },
  { key: "cloud_cover", label: "Cloud", colorVar: "--color-metric-temp", yAxisId: "right", frameField: "cloud_cover", overviewField: "", decimals: 0, unit: "%" },
  { key: "airmass", label: "Airmass", colorVar: "--color-metric-temp", yAxisId: "right", frameField: "airmass", overviewField: "", decimals: 2 },
];

export function getMetricColor(colorVar: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(colorVar).trim();
}

export function getMetricDef(key: string): MetricDefinition | undefined {
  return METRIC_DEFINITIONS.find((m) => m.key === key);
}
