import type { Component } from "solid-js";
import { MosaicsTab } from "../components/settings/MosaicsTab";
import HelpPopover from "../components/HelpPopover";
import { useSettingsContext } from "../components/SettingsProvider";
import { contentWidthClass } from "../utils/format";

const MosaicsPage: Component = () => {
  const ctx = useSettingsContext();
  return (
    <div class={`p-4 space-y-6 ${contentWidthClass(ctx.contentWidth())}`}>
      <div class="flex items-center gap-2">
        <h1 class="text-xl font-semibold tracking-tight text-theme-text-primary">Mosaics</h1>
        <HelpPopover>
          <p class="text-sm text-theme-text-secondary">
            Mosaics group multiple targets that together form a larger image (e.g., multi-panel nebula projects).
          </p>
          <p class="text-sm text-theme-text-secondary">
            GalactiLog can auto-detect mosaic panels by looking for keywords like "Panel" or "P" in target names. Configure detection keywords in the keyword list.
          </p>
          <ul class="list-disc list-inside space-y-1">
            <li class="text-sm text-theme-text-secondary">
              <strong class="text-theme-text-primary">Run Detection</strong> scans for new mosaic candidates. Review suggestions and accept or dismiss them.
            </li>
            <li class="text-sm text-theme-text-secondary">
              You can also <strong class="text-theme-text-primary">create mosaics manually</strong> and add panels by searching for existing targets.
            </li>
            <li class="text-sm text-theme-text-secondary">
              Each mosaic tracks combined integration time and frame counts across all its panels.
            </li>
          </ul>
        </HelpPopover>
      </div>
      <MosaicsTab />
    </div>
  );
};

export default MosaicsPage;
