import { describe, it, expect, vi } from "vitest";
import { render, fireEvent } from "@solidjs/testing-library";
import WbppFooter, { type CopyBlocker, type WbppFooterProps } from "./WbppFooter";

const props = (overrides: Partial<WbppFooterProps> = {}): WbppFooterProps => ({
  frameCount: 1234,
  folderCount: 3,
  sizeBytes: 24_100_000_000,
  destination: "D:\\stacking\\M31",
  scriptDestination: null,
  permissionGranted: true,
  blockedBy: null,
  canBrowserCopy: true,
  copying: false,
  copyProgress: null,
  onCopy: () => {},
  onStop: () => {},
  scriptMenu: <button>Generate script</button>,
  ...overrides,
});

const primary = (container: HTMLElement): HTMLButtonElement | undefined =>
  Array.from(container.querySelectorAll("button")).find((b) =>
    /Copy |Choose a destination|Choose a source folder|Access denied|Grant access and copy|\d+ \/ \d+|Scanning/.test(
      b.textContent ?? "",
    ),
  ) as HTMLButtonElement | undefined;

describe("WbppFooter summary", () => {
  it("renders frame count, folder count and size", () => {
    const { container } = render(() => <WbppFooter {...props()} />);
    expect(container.textContent).toContain("1,234 frames");
    expect(container.textContent).toContain("3 folders");
    expect(container.textContent).toContain("24.1 GB");
  });

  it("pluralizes a single folder", () => {
    const { container } = render(() => <WbppFooter {...props({ folderCount: 1 })} />);
    expect(container.textContent).toContain("1 folder ");
    expect(container.textContent).toContain("1 folder ·");
    expect(container.textContent).not.toContain("1 folders");
  });

  it("uses tabular figures for the summary line", () => {
    const { container } = render(() => <WbppFooter {...props()} />);
    expect(container.querySelector(".tabular-nums")).not.toBeNull();
  });

  it("renders an em-dash and never 0 B when the size is unknown", () => {
    const { container } = render(() => <WbppFooter {...props({ sizeBytes: null })} />);
    expect(container.textContent).toContain("—");
    expect(container.textContent).not.toContain("0 B");
  });

  it("renders the destination line, and omits it when there is none", () => {
    const { container } = render(() => <WbppFooter {...props()} />);
    expect(container.textContent).toContain("→ D:\\stacking\\M31");

    const { container: none } = render(() => (
      <WbppFooter {...props({ destination: null, scriptDestination: null })} />
    ));
    expect(none.textContent).not.toContain("→");
  });

  it("labels the copy and script destinations separately when both exist", () => {
    // Browser copy and script generation write to DIFFERENT places. An unlabelled
    // "→ X" showing only one of them let a Chromium user read the copy handle's
    // name as the path their generated script would write to.
    const { container } = render(() => (
      <WbppFooter {...props({ scriptDestination: "Z:\\Astro\\_WBPP_staging\\M31" })} />
    ));
    expect(container.textContent).toContain("Copy → D:\\stacking\\M31");
    expect(container.textContent).toContain("Script → Z:\\Astro\\_WBPP_staging\\M31");
  });

  it("still shows the script destination when there is no copy destination", () => {
    // The non-Chromium case: no browser copy at all, but the script still writes
    // somewhere and the user must be able to see where.
    const { container } = render(() => (
      <WbppFooter
        {...props({
          destination: null,
          canBrowserCopy: false,
          scriptDestination: "/mnt/astro/_WBPP_staging/M31",
        })}
      />
    ));
    expect(container.textContent).toContain("Script → /mnt/astro/_WBPP_staging/M31");
    expect(container.textContent).not.toContain("Copy →");
  });
});

describe("WbppFooter primary action", () => {
  it("labels the primary with the frame count and emits onCopy", () => {
    const onCopy = vi.fn();
    const { container } = render(() => <WbppFooter {...props({ onCopy })} />);
    const btn = primary(container)!;
    expect(btn.textContent).toBe("Copy 1,234 frames");
    expect(btn.disabled).toBe(false);
    fireEvent.click(btn);
    expect(onCopy).toHaveBeenCalledTimes(1);
  });

  it("disables the primary and asks for a destination when none is chosen", () => {
    const { container } = render(() => (
      <WbppFooter {...props({ destination: null, blockedBy: "destination" })} />
    ));
    const btn = primary(container)!;
    expect(btn.textContent).toBe("Choose a destination");
    expect(btn.disabled).toBe(true);
  });

  it("offers to grant access and copy in one click when permission is missing", () => {
    const onCopy = vi.fn();
    const { container } = render(() => (
      <WbppFooter {...props({ permissionGranted: false, onCopy })} />
    ));
    const btn = primary(container)!;
    expect(btn.textContent).toBe("Grant access and copy");
    expect(btn.disabled).toBe(false);
    fireEvent.click(btn);
    expect(onCopy).toHaveBeenCalledTimes(1);
  });

  it("disables the primary whenever a copy cannot proceed, destination or not", () => {
    // A destination alone is not enough: without a source folder, or with a denied
    // permission, the click can only fail into the error banner. The footer owns no
    // such logic -- the parent decides and passes blockedBy.
    const onCopy = vi.fn();
    const { container } = render(() => (
      <WbppFooter {...props({ blockedBy: "source", permissionGranted: false, onCopy })} />
    ));
    const btn = primary(container)!;
    expect(btn.disabled).toBe(true);
    fireEvent.click(btn);
    expect(onCopy).not.toHaveBeenCalled();
  });

  it("names the actual blocker rather than a plausible-looking other step", () => {
    // Each label states the user's next move. "Grant access and copy" next to a
    // missing source folder named a step that was not the blocker, and the mirror
    // case ("Choose a destination") made the asymmetry obvious.
    const cases: [CopyBlocker, string][] = [
      ["destination", "Choose a destination"],
      ["source", "Choose a source folder"],
      ["permission", "Access denied. Choose the folder again."],
    ];
    for (const [blockedBy, label] of cases) {
      const { container } = render(() => (
        <WbppFooter {...props({ blockedBy, permissionGranted: false })} />
      ));
      const btn = primary(container)!;
      expect(btn.textContent).toBe(label);
      expect(btn.disabled).toBe(true);
    }
  });

  it("offers the copy once nothing blocks it", () => {
    const { container } = render(() => <WbppFooter {...props({ blockedBy: null })} />);
    const btn = primary(container)!;
    expect(btn.textContent).toBe("Copy 1,234 frames");
    expect(btn.disabled).toBe(false);
  });

  it("shows a ready chip only when permission is granted and copy is supported", () => {
    const { container } = render(() => <WbppFooter {...props()} />);
    expect(container.textContent).toContain("Browser access ready");

    const { container: pending } = render(() => (
      <WbppFooter {...props({ permissionGranted: false })} />
    ));
    expect(pending.textContent).not.toContain("Browser access ready");
  });
});

describe("WbppFooter while copying", () => {
  it("shows progress on the primary and a Stop that calls onStop", () => {
    const onStop = vi.fn();
    const { container, getByText } = render(() => (
      <WbppFooter
        {...props({
          copying: true,
          copyProgress: { done: 12, total: 400, label: "LIGHT_M31_001.fits" },
          onStop,
        })}
      />
    ));
    expect(container.textContent).toContain("12 / 400 - LIGHT_M31_001.fits");

    const stop = getByText("Stop") as HTMLButtonElement;
    fireEvent.click(stop);
    expect(onStop).toHaveBeenCalledTimes(1);
  });

  it("reads as scanning before the total is known", () => {
    const { container } = render(() => (
      <WbppFooter
        {...props({ copying: true, copyProgress: { done: 0, total: 0, label: "" } })}
      />
    ));
    expect(container.textContent).toContain("Scanning...");
  });

  it("hides the ready chip while copying", () => {
    const { container } = render(() => (
      <WbppFooter {...props({ copying: true, copyProgress: null })} />
    ));
    expect(container.textContent).not.toContain("Browser access ready");
  });

  it("has no Stop button when idle", () => {
    const { queryByText } = render(() => <WbppFooter {...props()} />);
    expect(queryByText("Stop")).toBeNull();
  });
});

describe("WbppFooter without browser copy support", () => {
  it("hides the copy button and explains the fallback", () => {
    const { container } = render(() => <WbppFooter {...props({ canBrowserCopy: false })} />);
    expect(primary(container)).toBe(undefined);
    expect(container.textContent).toContain(
      "In-browser copy needs a Chromium browser (Chrome/Edge) over HTTPS or localhost.",
    );
    expect(container.textContent).toContain(
      'Use "Generate script" to download a copy script instead.',
    );
    // The old wording pointed "below" at a section that is now beside it.
    expect(container.textContent).not.toContain("below");
  });

  it("still renders the script menu", () => {
    const { queryByText } = render(() => <WbppFooter {...props({ canBrowserCopy: false })} />);
    expect(queryByText("Generate script")).not.toBeNull();
  });
});

describe("WbppFooter composition", () => {
  it("renders the scriptMenu prop as given", () => {
    const { queryByText } = render(() => (
      <WbppFooter {...props({ scriptMenu: <span>menu-slot</span> })} />
    ));
    expect(queryByText("menu-slot")).not.toBeNull();
  });

  it("has no Cancel or Close button — the dialog owns dismissal", () => {
    const { container } = render(() => <WbppFooter {...props()} />);
    const labels = Array.from(container.querySelectorAll("button")).map((b) => b.textContent);
    expect(labels.some((l) => /Cancel|Close/i.test(l ?? ""))).toBe(false);
  });

  it("repeats modal-surface on the sticky element so content cannot bleed through", () => {
    const { container } = render(() => <WbppFooter {...props()} />);
    const root = container.firstElementChild as HTMLElement;
    expect(root.className).toContain("modal-surface");
    expect(root.className).toContain("sticky");
    expect(root.className).toContain("border-t");
  });
});
