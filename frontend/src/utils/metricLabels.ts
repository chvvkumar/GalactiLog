// Canonical display labels (with units) for the analysis metric keys.
// Single source of truth for select options, chart axis titles, and stats
// card labels, so every surface shows the same unit annotation.
//
// Unit notes:
// - HFR is measured in pixels and is only comparable within a single optical
//   train. Cross-telescope comparison requires FWHM in arcseconds.
// - FWHM is stored in arcseconds (sourced from the NINA Session Metadata CSV)
//   and is comparable across optical trains.
import { ARCSEC } from "./format";

export const METRIC_LABELS: Record<string, string> = {
  humidity: "Humidity (%)",
  wind_speed: "Wind Speed",
  ambient_temp: "Ambient Temp (°C)",
  dew_point: "Dew Point (°C)",
  pressure: "Pressure (hPa)",
  cloud_cover: "Cloud Cover (%)",
  sky_quality: "Sky Quality (SQM)",
  focuser_temp: "Focuser Temp (°C)",
  airmass: "Airmass",
  sensor_temp: "Sensor Temp (°C)",
  hfr: "HFR (px)",
  fwhm: `FWHM (${ARCSEC})`,
  eccentricity: "Eccentricity",
  guiding_rms: `Guiding RMS (${ARCSEC})`,
  guiding_rms_ra: `Guiding RA RMS (${ARCSEC})`,
  guiding_rms_dec: `Guiding DEC RMS (${ARCSEC})`,
  detected_stars: "Detected Stars",
  adu_mean: "ADU Mean",
  adu_median: "ADU Median",
  adu_stdev: "ADU StDev",
  phd2_rms_total: `PHD2 RMS Total (${ARCSEC})`,
  phd2_rms_ra: `PHD2 RMS RA (${ARCSEC})`,
  phd2_rms_dec: `PHD2 RMS Dec (${ARCSEC})`,
  phd2_star_lost_pct: "PHD2 Star Lost (%)",
  phd2_snr_mean: "PHD2 Guide SNR",
};

// Unit suffix appended directly after a formatted value ("2.31 px", "0.85″").
export const METRIC_UNITS: Record<string, string> = {
  humidity: "%",
  ambient_temp: "°C",
  dew_point: "°C",
  pressure: " hPa",
  cloud_cover: "%",
  focuser_temp: "°C",
  sensor_temp: "°C",
  hfr: " px",
  guiding_rms: ARCSEC,
  guiding_rms_ra: ARCSEC,
  guiding_rms_dec: ARCSEC,
  phd2_rms_total: ARCSEC,
  phd2_rms_ra: ARCSEC,
  phd2_rms_dec: ARCSEC,
  phd2_star_lost_pct: "%",
};

// Night-level PHD2 X metrics, accepted by the correlation endpoint only.
export const PHD2_X_METRICS = [
  "phd2_rms_total", "phd2_rms_ra", "phd2_rms_dec", "phd2_star_lost_pct", "phd2_snr_mean",
];

export const PHD2_METRIC_NOTE =
  "Night-level PHD2 figures joined by rig and imaging night; nights with no mapped PHD2 profile are omitted.";

export function metricLabel(key: string): string {
  return METRIC_LABELS[key] ?? key;
}

export function metricOptions(keys: string[]): { value: string; label: string }[] {
  return keys.map((value) => ({ value, label: metricLabel(value) }));
}

// Disclosure text for surfaces that plot pixel-domain HFR across potentially
// different optical trains.
export const PIXEL_METRIC_NOTE =
  "HFR is measured in pixels and is only comparable within a single optical train. " +
  "Use FWHM in arcseconds for cross-telescope comparison.";
