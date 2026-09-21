import { Component, Show } from "solid-js";

// Rendered when an analysis response reports mixed_plate_scales. The flag is
// absent on older cached payloads, so undefined counts as false.
const PlateScaleWarning: Component<{ show: boolean | undefined }> = (props) => (
  <Show when={props.show === true}>
    <div role="alert" class="text-sm px-3 py-2 mb-3 rounded bg-theme-warning/10 text-theme-warning border border-theme-warning/20">
      The selected frames span more than one plate scale. HFR in pixels is not comparable across optical trains.
      Filter to one telescope and camera, or use the Compare tab, which converts to arcseconds.
    </div>
  </Show>
);

export default PlateScaleWarning;
