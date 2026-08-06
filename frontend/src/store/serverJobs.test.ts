import { describe, it, expect, vi } from "vitest";

vi.mock("../api/generated/client", () => ({
  apiClient: { GET: vi.fn() },
}));

import { taskLabel, serverJobToActiveJob, type ServerJob } from "./serverJobs";
import { waitingLabel } from "../components/JobMonitor";

describe("taskLabel", () => {
  it("maps known task names to human labels", () => {
    expect(taskLabel("app.worker.tasks.correlate_phd2_images")).toBe(
      "Matching guiding to frames"
    );
    expect(taskLabel("recompute_session_dates")).toBe("Recomputing session dates");
  });

  it("prettifies unknown names instead of showing raw dotted paths", () => {
    expect(taskLabel("app.worker.tasks.rebuild_star_index")).toBe("Rebuild star index");
    expect(taskLabel("some_new_thing_task")).toBe("Some new thing");
  });
});

describe("serverJobToActiveJob", () => {
  const base: ServerJob = {
    task_id: "abc-123",
    name: "app.worker.tasks.correlate_phd2_images",
    state: "queued",
    queued_at: 1_000_000,
  };

  it("marks queued rows waiting, keyed like track() rows for dedupe", () => {
    const job = serverJobToActiveJob(base);
    expect(job.id).toBe("celery:abc-123");
    expect(job.state).toBe("waiting");
    expect(job.startedAt).toBe(1_000_000_000);
    expect(job.cancelable).toBe(false);
  });

  it("anchors running rows to started_at and parses eta", () => {
    const job = serverJobToActiveJob({
      ...base,
      state: "running",
      started_at: 1_000_050,
      eta: "2026-08-05T21:00:00+00:00",
    });
    expect(job.state).toBe("running");
    expect(job.startedAt).toBe(1_000_050_000);
    expect(job.etaMs).toBe(Date.parse("2026-08-05T21:00:00+00:00"));
  });
});

describe("waitingLabel", () => {
  const job = serverJobToActiveJob({
    task_id: "x",
    name: "recompute_session_dates",
    state: "queued",
    queued_at: 1_000,
  });

  it("counts up from queue time", () => {
    expect(waitingLabel(job, 1_000_000 + 32_000)).toBe("queued 32s ago");
    expect(waitingLabel(job, 1_000_000 + 3 * 60_000)).toBe("queued 3m ago");
  });

  it("counts down to a future eta", () => {
    const withEta = { ...job, etaMs: 2_000_000 };
    expect(waitingLabel(withEta, 1_988_000)).toBe("starts in 12s");
  });

  it("falls back to queue age once the eta has passed", () => {
    const withEta = { ...job, etaMs: 1_500_000 };
    expect(waitingLabel(withEta, 1_600_000)).toBe("queued 10m ago");
  });
});
