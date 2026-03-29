import { type ParentProps, type Component, Show } from "solid-js";
import { Navigate } from "@solidjs/router";
import { useAuth } from "./AuthProvider";

const ProtectedRoute: Component<ParentProps> = (props) => {
  const { user, loading } = useAuth();

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
      </Show>
    </Show>
  );
};

export default ProtectedRoute;
