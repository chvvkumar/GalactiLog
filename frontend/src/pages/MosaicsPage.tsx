import type { Component } from "solid-js";
import { MosaicsTab } from "../components/settings/MosaicsTab";
import { useSettingsContext } from "../components/SettingsProvider";
import { contentWidthClass } from "../utils/format";

const MosaicsPage: Component = () => {
  const ctx = useSettingsContext();
  return (
    <div class={`p-4 space-y-6 ${contentWidthClass(ctx.contentWidth())}`}>
      <h1 class="text-xl font-semibold tracking-tight text-theme-text-primary">Mosaics</h1>
      <MosaicsTab />
    </div>
  );
};

export default MosaicsPage;
