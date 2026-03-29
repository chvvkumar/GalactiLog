import { createSignal } from "solid-js";
import { api } from "../api/client";
import type { GraphSettings } from "../types";

const DEFAULT_GRAPH_SETTINGS: GraphSettings = {
  enabled_metrics: ["hfr", "eccentricity", "fwhm", "guiding_rms"],
  enabled_filters: ["overall"],
  session_chart_expanded: false,
  target_chart_expanded: false,
};

const [graphSettings, setGraphSettings] = createSignal<GraphSettings>(DEFAULT_GRAPH_SETTINGS);
let loaded = false;

export function useGraphSettings() {
  return {
    graphSettings,

    async loadGraphSettings() {
      if (loaded) return;
      try {
        const resp = await api.getSettings();
        if (resp.graph) {
          setGraphSettings(resp.graph);
        }
        loaded = true;
      } catch {
        // Use defaults on error
      }
    },

    async saveGraphSettings(updates: Partial<GraphSettings>) {
      const current = graphSettings();
      const next = { ...current, ...updates };
      setGraphSettings(next);
      try {
        await api.updateGraph(next);
      } catch {
        setGraphSettings(current);
      }
    },

    toggleMetric(metric: string) {
      const current = graphSettings();
      const metrics = current.enabled_metrics.includes(metric)
        ? current.enabled_metrics.filter((m) => m !== metric)
        : [...current.enabled_metrics, metric];
      const next = { ...current, enabled_metrics: metrics };
      setGraphSettings(next);
      api.updateGraph(next).catch(() => setGraphSettings(current));
    },

    toggleFilter(filter: string) {
      const current = graphSettings();
      const filters = current.enabled_filters.includes(filter)
        ? current.enabled_filters.filter((f) => f !== filter)
        : [...current.enabled_filters, filter];
      const next = { ...current, enabled_filters: filters };
      setGraphSettings(next);
      api.updateGraph(next).catch(() => setGraphSettings(current));
    },
  };
}
