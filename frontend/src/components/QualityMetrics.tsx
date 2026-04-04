import { Component, Show } from "solid-js";
import { formatIntegration } from "../utils/format";

const QualityMetrics: Component<{
  hfr: number | null;
  eccentricity: number | null;
  frameCount: number;
  integrationSeconds: number;
}> = (props) => {
  return (
    <div class="grid grid-cols-2 gap-3">
      <MetricBox label="Frames" value={String(props.frameCount)} />
      <MetricBox label="Integration" value={formatIntegration(props.integrationSeconds)} />
      <Show when={props.hfr != null}>
        <MetricBox label="Median HFR" value={props.hfr!.toFixed(2)} />
      </Show>
      <Show when={props.eccentricity != null}>
        <MetricBox label="Eccentricity" value={props.eccentricity!.toFixed(2)} />
      </Show>
    </div>
  );
};

function MetricBox(props: { label: string; value: string }) {
  return (
    <div class="bg-theme-base rounded p-2">
      <div class="text-caption text-theme-text-secondary">{props.label}</div>
      <div class="text-theme-text-primary font-semibold text-sm">{props.value}</div>
    </div>
  );
}

export default QualityMetrics;
