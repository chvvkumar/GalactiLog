import { Component, Show } from "solid-js";
import { formatArcsec } from "../utils/format";

/**
 * Median FWHM cell shared by Equipment Performance and Equipment Inventory.
 *
 * FWHM is always arcseconds: it comes from the NINA Session Metadata CSV
 * (Hocus Focus), never from a pixel-domain header, so it is never multiplied
 * by the plate scale. Coverage is partial, so the count of frames that
 * actually carry an FWHM is shown next to the median as secondary text.
 */
const FwhmValue: Component<{ value: number | null | undefined; count?: number }> = (props) => (
  <Show when={props.value != null} fallback={<>&#8212;</>}>
    <span class="tabular-nums">{formatArcsec(props.value)}</span>
    <Show when={props.count}>
      <span class="ml-1 text-tiny text-theme-text-tertiary tabular-nums whitespace-nowrap">
        n={props.count!.toLocaleString()}
      </span>
    </Show>
  </Show>
);

export default FwhmValue;
