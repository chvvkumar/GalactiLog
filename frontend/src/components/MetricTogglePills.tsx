import { For } from "solid-js";
import { METRIC_DEFINITIONS, getMetricColor } from "../utils/chartConfig";
import { useSettingsContext } from "./SettingsProvider";
import Toggle from "./ui/Toggle";

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
            <Toggle
              active={isActive()}
              color={color()}
              onClick={() => toggleMetric(metric.key)}
            >
              {metric.label}
            </Toggle>
          );
        }}
      </For>
    </div>
  );
}
