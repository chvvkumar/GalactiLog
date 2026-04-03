import type { Component } from "solid-js";
import { MosaicsTab } from "../components/settings/MosaicsTab";

const MosaicsPage: Component = () => {
  return (
    <div class="p-4 mx-auto space-y-6 max-w-6xl">
      <h1 class="text-xl font-semibold tracking-tight text-theme-text-primary">Mosaics</h1>
      <MosaicsTab />
    </div>
  );
};

export default MosaicsPage;
