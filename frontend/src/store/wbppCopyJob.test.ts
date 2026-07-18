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
      opts.onProgress(5, 10, "2025-01-01: frame.fits");
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

  it("ignores a second start while a copy is running", async () => {
    let resolveCopy!: (r: { copied: number; destinationName: string }) => void;
    vi.mocked(runBrowserCopy).mockImplementation(
      () => new Promise((res) => { resolveCopy = res; }),
    );
    const p = startWbppCopy(args);
    await startWbppCopy(args);
    expect(vi.mocked(runBrowserCopy)).toHaveBeenCalledTimes(1);
    resolveCopy({ copied: 0, destinationName: "d" });
    await p;
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
