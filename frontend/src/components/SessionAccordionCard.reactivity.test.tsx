import { describe, it, expect } from "vitest";
import { render, fireEvent } from "@solidjs/testing-library";
import { createSignal, For } from "solid-js";
import {
  madZ,
  bandForZ,
  bandToCellClass,
  type GroupBaseline,
} from "../utils/frameQuality";

// Regression guard for the Per-Frame Data table reactivity bug.
//
// In SessionAccordionCard's renderFrameTable, each row is produced by a <For>
// callback. <For> does NOT re-run its body when a signal changes, so any
// mode-dependent color derivation must be a THUNK that is CALLED inside the JSX
// attribute (e.g. class={bandToCellClass(bandForZ(zHfr()))}). If instead the
// derivation is a plain const read once at row-creation time, the cell color
// freezes and never updates when the "Compare to" baseline toggle flips.
//
// This test reproduces that exact binding shape with the real frameQuality
// utilities and asserts the cell class re-tracks the baseline signal. It fails
// against the const pattern and passes against the thunk pattern.

interface MiniFrame {
  median_hfr: number;
}

// Two baselines chosen so the same HFR value lands in different color bands:
//  - session: z = (2.8 - 2.1) / 0.37 ~ 1.89  -> "watch" -> text-theme-warning
//  - rig:     z = (2.8 - 2.8) / 0.50 = 0      -> "neutral" -> text-theme-text-primary
const sessionBaseline: GroupBaseline = {
  median_hfr: { median: 2.1, mad: 0.37, n: 10 },
};
const rigBaseline: GroupBaseline = {
  median_hfr: { median: 2.8, mad: 0.5, n: 20 },
};

const frame: MiniFrame = { median_hfr: 2.8 };

function FrameTablePattern() {
  const [baselineMode, setBaselineMode] = createSignal<"session" | "rig">("session");
  const baselineFor = () =>
    baselineMode() === "session" ? sessionBaseline : rigBaseline;

  return (
    <div>
      <button data-testid="toggle-rig" onClick={() => setBaselineMode("rig")}>
        This rig overall
      </button>
      <table>
        <tbody>
          <For each={[frame]}>
            {(f) => {
              // Mirror the fixed pattern: mode-dependent derivation is a thunk
              // and is invoked inside the class attribute so it re-tracks.
              const zHfr = () => madZ(f.median_hfr, baselineFor()?.median_hfr);
              return (
                <tr>
                  <td
                    data-testid="hfr-cell"
                    class={bandToCellClass(bandForZ(zHfr()))}
                  >
                    {f.median_hfr.toFixed(2)}
                  </td>
                </tr>
              );
            }}
          </For>
        </tbody>
      </table>
    </div>
  );
}

describe("Per-Frame table baseline-toggle reactivity", () => {
  it("recolors the cell when the comparison baseline changes", () => {
    const { getByTestId } = render(() => <FrameTablePattern />);
    const cell = getByTestId("hfr-cell");

    // Session baseline -> "watch" band.
    expect(cell.className).toBe("text-theme-warning");

    fireEvent.click(getByTestId("toggle-rig"));

    // Rig baseline -> "neutral" band. The class must have re-evaluated.
    expect(cell.className).toBe("text-theme-text-primary");
    expect(cell.className).not.toBe("text-theme-warning");
  });
});
