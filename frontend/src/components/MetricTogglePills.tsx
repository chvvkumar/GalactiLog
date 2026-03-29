import { For } from "solid-js";
import { METRIC_DEFINITIONS, getMetricColor } from "../utils/chartConfig";
import { useSettingsContext } from "./SettingsProvider";

interface Props {
  availableMetrics?: string[];
}

export default function MetricTogglePills(props: Props) {
  const { graphSettings, toggleMetric } = useSettingsContext();

  const metrics = () => {
    if (props.availableMetrics) {
      return METRIC_DEFINITIONS.filter((m) => props.availableMetrics!.includes(m.key));
    }
    return METRIC_DEFINITIONS;
  };

  return (
    <div class="flex flex-wrap gap-1.5">
      <For each={metrics()}>
        {(metric) => {
          const isActive = () => graphSettings().enabled_metrics.includes(metric.key);
          const color = () => getMetricColor(metric.colorVar);
          return (
            <button
              class="px-2 py-0.5 rounded text-caption font-medium border transition-colors cursor-pointer"
              style={{
                "border-color": isActive() ? color() : "var(--color-border-default)",
                "background-color": isActive() ? `${color()}22` : "var(--color-bg-elevated)",
                color: isActive() ? color() : "var(--color-text-tertiary)",
              }}
              onClick={() => toggleMetric(metric.key)}
            >
              {metric.label}
            </button>
          );
        }}
      </For>
    </div>
  );
}
