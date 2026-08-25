import { type ParentProps, type Component, Show, lazy } from "solid-js";
import { Navigate } from "@solidjs/router";
import { useAuth } from "./AuthProvider";
import { useSettingsContext } from "./SettingsProvider";

const SetupWizard = lazy(() => import("./setup/SetupWizard"));

/**
 * Gate for the first-run wizard. Declared here rather than in SetupWizard.tsx
 * so ProtectedRoute can decide without statically importing the lazy chunk.
 */
export function shouldShowWizard(
  isAdmin: boolean,
  setupComplete: boolean,
  wizardRequested: boolean,
): boolean {
  return isAdmin && (!setupComplete || wizardRequested);
}

const ProtectedRoute: Component<ParentProps> = (props) => {
  const { user, loading, isAdmin } = useAuth();
  const { setupComplete, wizardRequested } = useSettingsContext();

  return (
    <Show
      when={!loading()}
      fallback={
        <div class="flex items-center justify-center min-h-[60vh]">
          <span class="text-theme-text-secondary text-sm">Loading...</span>
        </div>
      }
    >
      <Show when={user()} fallback={<Navigate href="/login" />}>
        {props.children}
        <Show when={shouldShowWizard(isAdmin(), setupComplete(), wizardRequested())}>
          <SetupWizard />
        </Show>
      </Show>
    </Show>
  );
};

export default ProtectedRoute;
