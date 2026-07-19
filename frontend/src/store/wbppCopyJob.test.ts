import { describe, it, expect, vi, beforeEach } from "vitest";

vi.mock("../lib/wbppBrowserCopy", () => {
  class CopyCancelledError extends Error {
    constructor() {
      super("cancelled");
      this.name = "CopyCancelledError";
    }
  }
  return { runBrowserCopy: vi.fn(), CopyCancelledError };
});
vi.mock("../components/Toast", () => ({ showToast: vi.fn() }));

import { runBrowserCopy, CopyCancelledError } from "../lib/wbppBrowserCopy";
import { showToast } from "../components/Toast";
import {
  startWbppCopy,
  stopWbppCopy,
  wbppCopyRunning,
  wbppCopyDone,
  wbppCopyTotal,
  wbppCopyError,
  wbppCopyFinished,
  wbppCopyActiveJob,
  wbppCopySpeed,
} from "./wbppCopyJob";

const args = {
  rootHandle: {},
  destHandle: {},
  operations: [],
  exclusions: [],
  excludedSourceRelatives: [],
  targetName: "M31",
};

describe("wbppCopyJob lifecycle", () => {
  beforeEach(() => {
    vi.mocked(runBrowserCopy).mockReset();
    vi.mocked(showToast).mockReset();
  });

  it("tracks progress while running and exposes an ActiveJob, then clears on completion", async () => {
    let resolveCopy!: (r: { copied: number; destinationName: string }) => void;
    vi.mocked(runBrowserCopy).mockImplementation((_root, _dest, opts) => {
      opts.onProgress(5, 10, "2025-01-01: frame.fits", 1024);
      return new Promise((res) => { resolveCopy = res; });
    });

    const p = startWbppCopy(args);
    expect(wbppCopyRunning()).toBe(true);
    expect(wbppCopyDone()).toBe(5);
    expect(wbppCopyTotal()).toBe(10);

    const job = wbppCopyActiveJob();
    expect(job?.id).toBe("wbpp-copy");
    expect(job?.category).toBe("wbpp_copy");
    expect(job?.label).toBe("WBPP copy: M31");
    expect(job?.progress).toBeCloseTo(0.5, 5);
    expect(job?.cancelable).toBe(true);

    resolveCopy({ copied: 10, destinationName: "staging" });
    await p;
    expect(wbppCopyRunning()).toBe(false);
    expect(wbppCopyFinished()).toBe(10);
    expect(wbppCopyActiveJob()).toBeNull();
    expect(vi.mocked(showToast).mock.calls[0][0]).toContain("Copied 10 files");
  });

  it("registers a beforeunload guard only while the copy runs", async () => {
    const addSpy = vi.spyOn(window, "addEventListener");
    const removeSpy = vi.spyOn(window, "removeEventListener");
    vi.mocked(runBrowserCopy).mockResolvedValue({ copied: 1, destinationName: "d" });

    await startWbppCopy(args);

    expect(addSpy.mock.calls.some(([type]) => type === "beforeunload")).toBe(true);
    expect(removeSpy.mock.calls.some(([type]) => type === "beforeunload")).toBe(true);
    addSpy.mockRestore();
    removeSpy.mockRestore();
  });

  it("treats cancellation as a clean stop, not an error", async () => {
    vi.mocked(runBrowserCopy).mockRejectedValue(new CopyCancelledError());
    await startWbppCopy(args);
    expect(wbppCopyRunning()).toBe(false);
    expect(wbppCopyError()).toBeNull();
  });

  it("records failures and surfaces a toast", async () => {
    vi.mocked(runBrowserCopy).mockRejectedValue(new Error("disk full"));
    await startWbppCopy(args);
    expect(wbppCopyError()).toContain("disk full");
    expect(vi.mocked(showToast)).toHaveBeenCalled();
  });

  it("ignores a second start while a copy is running, but toasts instead of failing silently", async () => {
    let resolveCopy!: (r: { copied: number; destinationName: string }) => void;
    vi.mocked(runBrowserCopy).mockImplementation(
      () => new Promise((res) => { resolveCopy = res; }),
    );
    const p = startWbppCopy(args);
    const doneBefore = wbppCopyDone();
    const totalBefore = wbppCopyTotal();

    await startWbppCopy({ ...args, targetName: "Different Target" });

    expect(vi.mocked(runBrowserCopy)).toHaveBeenCalledTimes(1);
    expect(vi.mocked(showToast)).toHaveBeenCalledWith(
      expect.stringContaining("already running"),
      "error",
      0,
    );
    // State from the in-flight copy must survive the rejected second call, not
    // be reset by it.
    expect(wbppCopyRunning()).toBe(true);
    expect(wbppCopyDone()).toBe(doneBefore);
    expect(wbppCopyTotal()).toBe(totalBefore);
    expect(wbppCopyActiveJob()?.label).toBe("WBPP copy: M31");

    resolveCopy({ copied: 0, destinationName: "d" });
    await p;
  });

  it("keeps state alive independent of any component: reattach reads the same live store", async () => {
    // Simulates the modal unmounting mid-copy and a later remount (or the job
    // monitor, which never mounts the modal at all) reading the same
    // module-level store -- there is nothing component-local to lose.
    let resolveCopy!: (r: { copied: number; destinationName: string }) => void;
    vi.mocked(runBrowserCopy).mockImplementation((_root, _dest, opts) => {
      opts.onProgress(3, 9, "in progress", 512);
      return new Promise((res) => { resolveCopy = res; });
    });

    const p = startWbppCopy(args);
    expect(wbppCopyRunning()).toBe(true);

    // "Unmount": nothing in the store references a component, so there is
    // nothing to tear down. A later "reattach" is just reading the same
    // accessors again.
    expect(wbppCopyRunning()).toBe(true);
    expect(wbppCopyDone()).toBe(3);
    expect(wbppCopyTotal()).toBe(9);
    expect(wbppCopyActiveJob()).not.toBeNull();

    resolveCopy({ copied: 9, destinationName: "d" });
    await p;
    expect(wbppCopyRunning()).toBe(false);
  });

  it("derives a windowed transfer rate from completed-file bytes", async () => {
    vi.useFakeTimers();
    try {
      let resolveCopy!: (r: { copied: number; destinationName: string }) => void;
      let progress!: (d: number, t: number, l: string, bytes: number) => void;
      vi.mocked(runBrowserCopy).mockImplementation((_root, _dest, opts) => {
        progress = opts.onProgress;
        return new Promise((res) => { resolveCopy = res; });
      });
      const p = startWbppCopy(args);

      // Window not yet filled (1 s elapsed < 3 s): cumulative average.
      // 125 MB in 1 s = 1000 Mbps, which crosses into the Gbps format.
      vi.advanceTimersByTime(1000);
      progress(1, 4, "s: a.fits", 125_000_000);
      expect(wbppCopySpeed()).toBe("1.0 Gbps");
      expect(wbppCopyActiveJob()?.subLabel).toBe("1 / 4 files · 1.0 Gbps");

      // Window filled (4 s elapsed): both samples sit inside the 3 s window,
      // so (125 + 50) MB / 3 s = 466.67 Mbps, shown as integer Mbps.
      vi.advanceTimersByTime(3000);
      progress(2, 4, "s: b.fits", 50_000_000);
      expect(wbppCopySpeed()).toBe("467 Mbps");

      // Old samples age out: 5 s later only the new 30 MB sample remains,
      // 30 MB / 3 s = 80 Mbps.
      vi.advanceTimersByTime(5000);
      progress(3, 4, "s: c.fits", 30_000_000);
      expect(wbppCopySpeed()).toBe("80 Mbps");

      resolveCopy({ copied: 4, destinationName: "d" });
      await p;
    } finally {
      vi.useRealTimers();
    }
  });

  it("mirrors progress into the tab title and restores it when the run settles", async () => {
    vi.useFakeTimers();
    const originalTitle = document.title;
    document.title = "GalactiLog · M31";
    try {
      let resolveCopy!: (r: { copied: number; destinationName: string }) => void;
      let progress!: (d: number, t: number, l: string, bytes: number) => void;
      vi.mocked(runBrowserCopy).mockImplementation((_root, _dest, opts) => {
        progress = opts.onProgress;
        return new Promise((res) => { resolveCopy = res; });
      });
      const p = startWbppCopy(args);

      // Before the rate exists (no time elapsed) the title carries counts only.
      progress(1, 4, "s: a.fits", 1_000_000);
      expect(document.title).toBe("1/4 — GalactiLog · M31");

      // Once a rate is available it joins the prefix; no nesting on later ticks.
      vi.advanceTimersByTime(1000);
      progress(2, 4, "s: b.fits", 124_000_000);
      expect(document.title).toBe("2/4 · 1.0 Gbps — GalactiLog · M31");

      resolveCopy({ copied: 4, destinationName: "d" });
      await p;
      expect(document.title).toBe("GalactiLog · M31");
    } finally {
      document.title = originalTitle;
      vi.useRealTimers();
    }
  });

  it("restores the tab title on cancel, and a second run does not nest prefixes", async () => {
    // Fake timers freeze Date.now, so no rate exists and the title stays
    // counts-only, keeping the assertions deterministic.
    vi.useFakeTimers();
    const originalTitle = document.title;
    document.title = "GalactiLog";
    try {
      // First run: cancelled mid-flight.
      let progress!: (d: number, t: number, l: string, bytes: number) => void;
      vi.mocked(runBrowserCopy).mockImplementation((_root, _dest, opts) => {
        progress = opts.onProgress;
        return new Promise((_res, reject) => {
          opts.signal?.addEventListener("abort", () => reject(new CopyCancelledError()));
        });
      });
      const p1 = startWbppCopy(args);
      progress(1, 8, "s: a.fits", 0);
      expect(document.title).toBe("1/8 — GalactiLog");
      stopWbppCopy();
      await p1;
      expect(document.title).toBe("GalactiLog");

      // Second run recaptures the clean title: exactly one prefix, then restore.
      let resolveCopy!: (r: { copied: number; destinationName: string }) => void;
      vi.mocked(runBrowserCopy).mockImplementation((_root, _dest, opts) => {
        progress = opts.onProgress;
        return new Promise((res) => { resolveCopy = res; });
      });
      const p2 = startWbppCopy(args);
      progress(3, 6, "s: b.fits", 0);
      expect(document.title).toBe("3/6 — GalactiLog");
      resolveCopy({ copied: 6, destinationName: "d" });
      await p2;
      expect(document.title).toBe("GalactiLog");
    } finally {
      document.title = originalTitle;
      vi.useRealTimers();
    }
  });

  it("stopWbppCopy aborts the in-flight signal", async () => {
    let capturedSignal: AbortSignal | undefined;
    vi.mocked(runBrowserCopy).mockImplementation((_r, _d, opts) => {
      capturedSignal = opts.signal;
      return new Promise((_res, reject) => {
        opts.signal?.addEventListener("abort", () => reject(new CopyCancelledError()));
      });
    });
    const p = startWbppCopy(args);
    stopWbppCopy();
    await p;
    expect(capturedSignal?.aborted).toBe(true);
    expect(wbppCopyRunning()).toBe(false);
  });
});
