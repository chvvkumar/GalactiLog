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

export async function emitWithToast(opts: EmitWithToastOptions): Promise<void> {
  showToast(opts.pendingLabel, "info", 120_000);

  let taskId: string;
  try {
    const result = await opts.action();
    taskId = result.task_id;
  } catch {
    dismissToast();
    showToast(opts.errorLabel, "error", 0);
    return;
  }

  track({
    id: taskId,
    category: opts.category,
    label: opts.taskLabel,
    subLabel: opts.taskSubLabel,
    timeout: opts.timeout ?? 300_000,
    onSuccess: () => {
      dismissToast();
      showToast(opts.successLabel, "success", 3000);
    },
    onFailure: (error) => {
      dismissToast();
      showToast(`${opts.errorLabel}: ${error}`, "error", 0);
    },
  });
}
