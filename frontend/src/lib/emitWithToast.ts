import { showToast, dismissToast } from "../components/Toast";
import { track } from "../store/taskPoller";
import type { ActiveJob } from "../types";

interface EmitWithToastOptions {
  action: () => Promise<{ task_id: string }>;
  pendingLabel: string;
  successLabel: string;
  errorLabel: string;
  category: ActiveJob["category"];
  taskLabel: string;
  taskSubLabel?: string;
  timeout?: number;
}

// Monotonic counter identifying the most recently invoked emitWithToast call.
// Each invocation captures its own id; only callbacks belonging to the most
// recent invocation are allowed to mutate the global toast slot. This prevents
// terminal callbacks from a previous (still-polling or just-completed) action
// from stomping on the toast that a freshly clicked action just created. The
// underlying Celery job tracking in `track()` is unaffected; only the toast
// surface is gated.
let latestEmitId = 0;

export async function emitWithToast(opts: EmitWithToastOptions): Promise<void> {
  const myId = ++latestEmitId;
  const isCurrent = () => myId === latestEmitId;

  showToast(opts.pendingLabel, "info", 120_000);

  let taskId: string;
  try {
    const result = await opts.action();
    taskId = result.task_id;
  } catch {
    if (!isCurrent()) return;
    dismissToast();
    showToast(opts.errorLabel, "error", 0);
    return;
  }

  // Backend may not return a task_id (older endpoints). In that case we
  // cannot poll for completion, so skip the activeJobs registration and
  // just show a fire-and-forget toast rather than stranding an entry in
  // "Now Running" that never clears.
  if (!taskId) {
    if (!isCurrent()) return;
    dismissToast();
    showToast(opts.successLabel, "info", 3000);
    return;
  }

  track({
    id: taskId,
    category: opts.category,
    label: opts.taskLabel,
    subLabel: opts.taskSubLabel,
    timeout: opts.timeout ?? 300_000,
    onSuccess: () => {
      if (!isCurrent()) return;
      dismissToast();
      showToast(opts.successLabel, "success", 3000);
    },
    onFailure: (error) => {
      if (!isCurrent()) return;
      dismissToast();
      showToast(`${opts.errorLabel}: ${error}`, "error", 0);
    },
  });
}
