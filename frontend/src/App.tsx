import { type Component, type ParentProps } from "solid-js";
import NavBar from "./components/NavBar";
import { Toast } from "./components/Toast";

const App: Component<ParentProps> = (props) => {
  return (
    <div class="min-h-screen bg-theme-base text-theme-text-primary">
      <NavBar />
      {props.children}
      <Toast />
    </div>
  );
};

export default App;
