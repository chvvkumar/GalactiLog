import { type Component, type ParentProps, Show } from "solid-js";
import { useLocation } from "@solidjs/router";
import NavBar from "./components/NavBar";
import { Toast } from "./components/Toast";

const App: Component<ParentProps> = (props) => {
  const location = useLocation();

  return (
    <div class="min-h-screen bg-theme-base text-theme-text-primary relative z-10">
      <Show when={location.pathname !== "/login"}>
        <NavBar />
      </Show>
      {props.children}
      <Toast />
    </div>
  );
};

export default App;
