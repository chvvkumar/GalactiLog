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
// recent invocation are allowed to mutate the toast surface. This prevents
// terminal callbacks from a previous (still-polling or just-completed) action
// from affecting the toast surface for a freshly clicked action.
let latestEmitId = 0;

// Cancel handle for the most recent in-flight `track()` call. When a newer
// emitWithToast supersedes it, we cancel the older poller to stop wasted
// network polling and remove the stale "Now Running" entry.
let activeCancel: (() => void) | null = null;

export async function emitWithToast(opts: EmitWithToastOptions): Promise<void> {
  const myId = ++latestEmitId;
  const isCurrent = () => myId === latestEmitId;

  // Supersede any previous in-flight tracker.
  if (activeCancel) {
    try { activeCancel(); } catch { /* ignore */ }
    activeCancel = null;
  }

  const pendingToastId = showToast(opts.pendingLabel, "info", 120_000);

  let taskId: string;
  try {
    const result = await opts.action();
    taskId = result.task_id;
  } catch {
    if (!isCurrent()) return;
    dismissToast(pendingToastId);
    showToast(opts.errorLabel, "error", 0);
    return;
  }

  // Backend may not return a task_id (older endpoints). In that case we
  // cannot poll for completion, so skip the activeJobs registration and
  // just show a fire-and-forget toast rather than stranding an entry in
  // "Now Running" that never clears.
  if (!taskId) {
    if (!isCurrent()) return;
    dismissToast(pendingToastId);
    showToast(opts.successLabel, "info", 3000);
    return;
  }

  const cancel = track({
    id: taskId,
    category: opts.category,
    label: opts.taskLabel,
    subLabel: opts.taskSubLabel,
    timeout: opts.timeout ?? 300_000,
    onSuccess: () => {
      if (activeCancel === cancel) activeCancel = null;
      if (!isCurrent()) return;
      dismissToast(pendingToastId);
      showToast(opts.successLabel, "success", 3000);
    },
    onFailure: (error) => {
      if (activeCancel === cancel) activeCancel = null;
      if (!isCurrent()) return;
      dismissToast(pendingToastId);
      showToast(`${opts.errorLabel}: ${error}`, "error", 0);
    },
    onTimeout: () => {
      // Client poller gave up; the backend task may still finish. Silently
      // dismiss the pending toast without surfacing a misleading failure.
      if (activeCancel === cancel) activeCancel = null;
      if (!isCurrent()) return;
      dismissToast(pendingToastId);
    },
  });
  activeCancel = cancel;
}
