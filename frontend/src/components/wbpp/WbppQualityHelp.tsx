import { Show, createSignal, type Component } from "solid-js";

// Inline help for the WBPP quality-filter toolbar. The glyph sits in the
// toolbar header; clicking it expands a help panel in normal document flow
// (basis-full wraps it to its own row below the header, pushing the chips and
// table down) instead of floating an overlay. A second click collapses it.
// Wording is plain text: no em dashes, commas instead.
const K_ROWS: { k: string; cut: string; note: string }[] = [
  { k: "1.0", cut: "~16%", note: "Data-rich broadband, keep only the best." },
  { k: "1.5 (default)", cut: "~7%", note: "Balanced." },
  { k: "2.0", cut: "~2%", note: "Scarce data, narrowband, few clear nights." },
  { k: "2.5 to 3.0", cut: "<1%", note: "Removes only ruined frames: clouds, wind, failed focus." },
];

const PANEL_ID = "wbpp-quality-help-panel";

const WbppQualityHelp: Component = () => {
  const [open, setOpen] = createSignal(false);

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-label="About the quality filter"
        aria-expanded={open()}
        aria-controls={PANEL_ID}
        class="inline-flex items-center justify-center w-6 h-6 rounded-full text-theme-text-tertiary hover:text-theme-text-primary hover:bg-theme-hover transition-colors cursor-pointer shrink-0"
      >
        <svg class="w-4 h-4" viewBox="0 0 20 20" fill="currentColor" aria-hidden="true">
          <path
            fill-rule="evenodd"
            d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7-4a1 1 0 11-2 0 1 1 0 012 0zM9 9a1 1 0 000 2v3a1 1 0 001 1h1a1 1 0 100-2v-3a1 1 0 00-1-1H9z"
            clip-rule="evenodd"
          />
        </svg>
      </button>

      <Show when={open()}>
        <section
          id={PANEL_ID}
          role="region"
          aria-label="Quality filter guide"
          class="basis-full w-full border border-theme-border rounded-[var(--radius-md)] bg-theme-surface p-4"
        >
          <div class="text-sm font-medium text-theme-text-primary mb-3">Quality filter guide</div>
          <div class="grid gap-x-6 gap-y-4 text-tiny leading-relaxed text-theme-text-secondary sm:grid-cols-2">
            <div class="space-y-4">
              <div class="space-y-2">
                <h3 class="text-xs font-semibold text-theme-text-primary">Filter modes</h3>
                <dl class="space-y-2">
                  <div>
                    <dt class="text-theme-text-primary">Global:</dt>
                    <dd>
                      one fixed threshold per metric for all frames. The app fills in a
                      starting value from your own frames, per telescope, camera, and filter.
                      Typing a value replaces it.
                    </dd>
                  </div>
                  <div>
                    <dt class="text-theme-text-primary">Per-session:</dt>
                    <dd>
                      each night gets its own threshold, calculated from that night's frames.
                      You set only k, which controls how strict every night's threshold is.
                    </dd>
                  </div>
                </dl>
              </div>

              <div class="space-y-2">
                <h3 class="text-xs font-semibold text-theme-text-primary">Reading the panel</h3>
                <dl class="space-y-2">
                  <div>
                    <dt class="text-theme-text-primary">The line under the toolbar</dt>
                    <dd>
                      where each automatic threshold came from, which filter and which night.
                      "pooled" in orange means fewer than 8 frames were available, so a
                      combined value is used instead.
                    </dd>
                  </div>
                  <div>
                    <dt class="text-theme-text-primary">Per-session rows</dt>
                    <dd>
                      one row per night, showing its threshold, frame count, and how many are
                      kept and cut. An asterisk marks nights with too few frames, which use the
                      combined threshold and ignore k.
                    </dd>
                  </div>
                  <div>
                    <dt class="text-theme-text-primary">Cell colors</dt>
                    <dd>
                      red, the frame is over the threshold and will be cut. Amber, within 8
                      percent of the threshold, kept but close. No color, well clear.
                    </dd>
                  </div>
                  <div>
                    <dt class="text-theme-text-primary">Star count</dt>
                    <dd>
                      works in reverse: its threshold is a minimum, frames with too few stars
                      are cut.
                    </dd>
                  </div>
                </dl>
              </div>
            </div>

            <div class="space-y-4">
              <div class="space-y-2">
                <h3 class="text-xs font-semibold text-theme-text-primary">Choosing k</h3>
                <table class="w-full text-tiny border-collapse">
                  <thead>
                    <tr class="text-theme-text-tertiary text-left">
                      <th class="font-semibold px-3 py-1.5">k</th>
                      <th class="font-semibold px-3 py-1.5">Cut share</th>
                      <th class="font-semibold px-3 py-1.5">Use when</th>
                    </tr>
                  </thead>
                  <tbody>
                    {K_ROWS.map((r) => (
                      <tr class="border-t border-theme-border/40 align-top">
                        <td class="px-3 py-1.5 tabular-nums whitespace-nowrap text-theme-text-primary">
                          {r.k}
                        </td>
                        <td class="px-3 py-1.5 tabular-nums whitespace-nowrap">{r.cut}</td>
                        <td class="px-3 py-1.5">{r.note}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                <p class="text-theme-text-tertiary">
                  Real cut rates run somewhat higher than these estimates.
                </p>
                <p>
                  WBPP already gives soft frames less weight during stacking, so when in doubt
                  cut less: a rejected usable frame is lost signal. Check yourself by blinking a
                  few rejected frames. They should look clearly bad. If they look fine, raise k.
                </p>
              </div>
            </div>
          </div>
        </section>
      </Show>
    </>
  );
};

export default WbppQualityHelp;
