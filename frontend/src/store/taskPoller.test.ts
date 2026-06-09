import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { pollTask } from "./taskPoller";

// Mock the api module so we don't need a real network connection
vi.mock("../api/client", () => ({
  api: {
    getTaskStatus: vi.fn(),
  },
}));

// Mock activeJobs store (used only by track(), not pollTask directly)
vi.mock("./activeJobs", () => ({
  registerCeleryJob: vi.fn(),
  unregisterCeleryJob: vi.fn(),
}));

import { api } from "../api/client";

describe("pollTask", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.mocked(api.getTaskStatus).mockReset();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("calls onSuccess when the task returns SUCCESS", async () => {
    vi.mocked(api.getTaskStatus).mockResolvedValue({
      task_id: "abc",
      state: "SUCCESS",
      result: { value: 42 },
    });

    const onSuccess = vi.fn();
    pollTask("abc", { onSuccess, interval: 500 });

    // advanceTimersByTimeAsync advances timers AND drains microtasks
    await vi.advanceTimersByTimeAsync(500);

    expect(onSuccess).toHaveBeenCalledOnce();
    expect(onSuccess).toHaveBeenCalledWith({ value: 42 });
  });

  it("calls onFailure when the task returns FAILURE", async () => {
    vi.mocked(api.getTaskStatus).mockResolvedValue({
      task_id: "abc",
      state: "FAILURE",
      result: { error: "something went wrong" },
    });

    const onFailure = vi.fn();
    pollTask("abc", { onFailure, interval: 500 });

    await vi.advanceTimersByTimeAsync(500);

    expect(onFailure).toHaveBeenCalledOnce();
    expect(onFailure).toHaveBeenCalledWith("something went wrong");
  });

  it("calls onTimeout and stops polling after the timeout window", async () => {
    vi.mocked(api.getTaskStatus).mockResolvedValue({
      task_id: "abc",
      state: "PENDING",
      result: null,
    });

    const onTimeout = vi.fn();
    const onSuccess = vi.fn();
    pollTask("abc", { onSuccess, onTimeout, interval: 1000, timeout: 3000 });

    await vi.advanceTimersByTimeAsync(3001);

    expect(onTimeout).toHaveBeenCalledOnce();
    expect(onSuccess).not.toHaveBeenCalled();
  });

  it("returned stop function halts polling", async () => {
    vi.mocked(api.getTaskStatus).mockResolvedValue({
      task_id: "abc",
      state: "SUCCESS",
      result: null,
    });

    const onSuccess = vi.fn();
    const stop = pollTask("abc", { onSuccess, interval: 500 });

    // Cancel before the first tick fires
    stop();

    await vi.advanceTimersByTimeAsync(500);

    expect(onSuccess).not.toHaveBeenCalled();
  });

  it("continues polling when the task is still PENDING", async () => {
    vi.mocked(api.getTaskStatus)
      .mockResolvedValueOnce({ task_id: "abc", state: "PENDING", result: null })
      .mockResolvedValueOnce({ task_id: "abc", state: "PENDING", result: null })
      .mockResolvedValueOnce({ task_id: "abc", state: "SUCCESS", result: "done" });

    const onSuccess = vi.fn();
    pollTask("abc", { onSuccess, interval: 500, timeout: 10000 });

    await vi.advanceTimersByTimeAsync(500);
    await vi.advanceTimersByTimeAsync(500);
    await vi.advanceTimersByTimeAsync(500);

    expect(onSuccess).toHaveBeenCalledOnce();
    expect(onSuccess).toHaveBeenCalledWith("done");
  });
});
