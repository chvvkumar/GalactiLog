import { type Component, type ParentProps, Show, createEffect } from "solid-js";
import { useLocation } from "@solidjs/router";
import NavBar from "./components/NavBar";
import { Toast } from "./components/Toast";
import { useAuth } from "./components/AuthProvider";
import {
  startActivityErrorsPoller,
  stopActivityErrorsPoller,
} from "./store/activityErrors";

const ErrorPollerMount: Component = () => {
  const { user } = useAuth();

  createEffect(() => {
    if (user() !== null) {
      startActivityErrorsPoller();
    } else {
      stopActivityErrorsPoller();
    }
  });

  return null;
};

const App: Component<ParentProps> = (props) => {
  const location = useLocation();

  return (
    <div class="min-h-screen bg-theme-base text-theme-text-primary relative z-10">
      <Show when={location.pathname !== "/login"}>
        <NavBar />
        <ErrorPollerMount />
      </Show>
      {props.children}
      <Toast />
    </div>
  );
};

export default App;
