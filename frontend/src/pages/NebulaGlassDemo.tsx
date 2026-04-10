import { For } from "solid-js";
import { Search, Calendar, Filter, Settings, Activity, Database, ChevronDown, Maximize2 } from "lucide-solid";

const GlassPanel = (props: { children: any; class?: string }) => (
  <div class={`bg-theme-surface border border-theme-border shadow-[var(--shadow-lg)] rounded-[var(--radius-lg)] ${props.class ?? ""}`}>
    {props.children}
  </div>
);

const rows = [
  { name: "M 109", des: "M 109", pal: ["L", "R", "G", "B", "H"], time: "25h 52m", date: "2026-04-06", goal: "NSP", note: "Finished imaging" },
  { name: "Pinwheel Galaxy", des: "M 101 - Pinwheel Galaxy", pal: ["L", "R", "G", "B", "Sii", "IR"], time: "40h 59m", date: "2026-03-29", goal: "ESSP", note: "Needs more integration" },
  { name: "Bode's Galaxy", des: "M 81 - Bode's Galaxy", pal: ["L", "R", "G", "B", "H", "IR"], time: "78h 49m", date: "2026-03-28", goal: "Okie-Tex", note: "Spent too much time on this" },
  { name: "UGC 6524", des: "NGC 3718 - UGC 6524", pal: ["L", "R", "G", "B"], time: "07h 48m", date: "2026-03-22", goal: "-", note: "-" },
  { name: "Coddington's Nebula", des: "IC 2574 - Coddington's Nebula", pal: ["L", "R", "G", "B", "H"], time: "27h 10m", date: "2026-03-10", goal: "-", note: "-" },
  { name: "Sh2 274", des: "PN A66 21", pal: ["R", "G", "B", "Sii", "H", "Oiii"], time: "06h 05m", date: "2026-02-28", goal: "-", note: "-" },
  { name: "Horsehead Nebula", des: "Horsehead Nebula", pal: ["R", "G", "B", "Sii", "H", "Oiii"], time: "11h 06m", date: "2026-02-28", goal: "-", note: "-" },
];

const filterBadgeClass = (filter: string): string => {
  switch (filter) {
    case "L":  return "bg-[var(--color-filter-l)]/10 text-[var(--color-filter-l)]";
    case "R":  return "bg-[var(--color-filter-r)]/10 text-[var(--color-filter-r)]";
    case "G":  return "bg-[var(--color-filter-g)]/10 text-[var(--color-filter-g)]";
    case "B":  return "bg-[var(--color-filter-b)]/10 text-[var(--color-filter-b)]";
    case "H":
    case "Ha": return "bg-[var(--color-filter-ha)]/10 text-[var(--color-filter-ha)]";
    case "Sii": return "bg-[var(--color-filter-sii)]/10 text-[var(--color-filter-sii)]";
    case "Oiii": return "bg-[var(--color-filter-oiii)]/10 text-[var(--color-filter-oiii)]";
    default:   return "bg-theme-elevated text-theme-text-secondary";
  }
};

export default function NebulaGlassDemo() {
  return (
    <div class="min-h-screen bg-theme-base text-theme-text-secondary font-sans overflow-hidden relative selection:bg-theme-accent/30">

      {/* Orbs are rendered by applyTheme() - no hardcoded background needed */}

      <div class="relative z-10 flex h-screen p-4 gap-4">

        {/* SIDEBAR */}
        <GlassPanel class="w-72 flex-col hidden md:flex">
          <div class="p-6 border-b border-theme-border">
            <h1 class="text-2xl font-bold bg-gradient-to-r from-theme-accent to-purple-400 bg-clip-text text-transparent flex items-center gap-2">
              <Database class="w-6 h-6 text-theme-accent" />
              GalactiLog
            </h1>
          </div>

          <div class="p-4 flex-1 overflow-y-auto space-y-6">
            {/* Stats */}
            <div class="grid grid-cols-2 gap-2 text-sm">
              <div class="bg-theme-elevated border border-theme-border rounded-[var(--radius-md)] p-3">
                <div class="text-theme-text-tertiary text-xs mb-1">Integration</div>
                <div class="font-medium text-theme-text-primary tabular-nums">1752h 07m</div>
              </div>
              <div class="bg-theme-elevated border border-theme-border rounded-[var(--radius-md)] p-3">
                <div class="text-theme-text-tertiary text-xs mb-1">Targets</div>
                <div class="font-medium text-theme-text-primary tabular-nums">124</div>
              </div>
            </div>

            {/* Search */}
            <div class="space-y-4">
              <div>
                <label class="text-xs font-semibold text-theme-text-tertiary uppercase tracking-wider mb-2 block">Search Targets</label>
                <div class="relative">
                  <Search class="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-theme-text-tertiary" />
                  <input
                    type="text"
                    placeholder="M31, NGC 7000..."
                    class="w-full bg-theme-input border border-theme-border rounded-[var(--radius-sm)] py-2 pl-9 pr-3 text-sm text-theme-text-primary placeholder:text-theme-text-tertiary focus:outline-none focus:border-theme-accent/50 focus:ring-1 focus:ring-theme-accent/50 transition-all"
                  />
                </div>
              </div>

              {/* Filter dropdowns */}
              <div class="space-y-2">
                <For each={["Object Type", "Date Range", "Filters", "Equipment"]}>
                  {(item) => (
                    <button class="w-full flex items-center justify-between p-2 hover:bg-theme-hover rounded-[var(--radius-sm)] transition-colors text-sm text-theme-text-secondary">
                      <span>{item}</span>
                      <ChevronDown class="w-4 h-4 text-theme-text-tertiary" />
                    </button>
                  )}
                </For>
              </div>

              {/* Filter badges */}
              <div>
                <label class="text-xs font-semibold text-theme-text-tertiary uppercase tracking-wider mb-2 block mt-4">Grouped</label>
                <div class="flex gap-2 text-xs">
                  <span class="px-2 py-1 bg-[var(--color-filter-ha)]/10 text-[var(--color-filter-ha)] border border-[var(--color-filter-ha)]/20 rounded-[var(--radius-sm)]">Ha</span>
                  <span class="px-2 py-1 bg-theme-elevated text-theme-text-secondary border border-theme-border rounded-[var(--radius-sm)]">IR</span>
                  <span class="px-2 py-1 bg-[var(--color-filter-sii)]/10 text-[var(--color-filter-sii)] border border-[var(--color-filter-sii)]/20 rounded-[var(--radius-sm)]">Sii</span>
                </div>
              </div>
            </div>
          </div>

          <div class="p-4 border-t border-theme-border">
            <button class="w-full py-2 bg-theme-elevated hover:bg-theme-hover border border-theme-border rounded-[var(--radius-sm)] text-sm transition-colors text-theme-text-secondary">
              Reset Filters
            </button>
          </div>
        </GlassPanel>

        {/* MAIN CONTENT */}
        <div class="flex-1 flex flex-col min-w-0 gap-4">

          {/* Top Bar */}
          <GlassPanel class="h-16 flex items-center justify-between px-6 shrink-0">
            <div class="flex gap-6 text-sm">
              <span class="text-theme-accent font-medium border-b-2 border-theme-accent py-5">Dashboard</span>
              <span class="text-theme-text-secondary hover:text-theme-text-primary cursor-pointer transition-colors py-5">Mosaics</span>
              <span class="text-theme-text-secondary hover:text-theme-text-primary cursor-pointer transition-colors py-5">Statistics</span>
              <span class="text-theme-text-secondary hover:text-theme-text-primary cursor-pointer transition-colors py-5">Analysis</span>
            </div>
            <div class="flex items-center gap-4 text-sm">
              <span class="text-theme-text-secondary">chvvkumar</span>
              <button class="text-theme-text-tertiary hover:text-theme-text-primary transition-colors">Sign out</button>
            </div>
          </GlassPanel>

          {/* Table Area */}
          <GlassPanel class="flex-1 flex flex-col overflow-hidden">
            <div class="p-4 border-b border-theme-border flex justify-between items-center">
              <span class="text-sm text-theme-text-secondary">Showing 1-25 of 124 targets</span>
              <div class="flex items-center gap-2">
                <span class="text-sm text-theme-text-secondary">25 / page</span>
              </div>
            </div>

            <div class="flex-1 overflow-auto">
              <table class="w-full text-left text-sm whitespace-nowrap">
                <thead class="bg-theme-elevated/50 sticky top-0 backdrop-blur-md z-10 border-b border-theme-border text-xs text-theme-text-tertiary font-semibold tracking-wider">
                  <tr>
                    <th class="p-4 font-medium">TARGET NAME</th>
                    <th class="p-4 font-medium">DESIGNATION</th>
                    <th class="p-4 font-medium">PALETTE</th>
                    <th class="p-4 font-medium text-right">INTEGRATION TIME</th>
                    <th class="p-4 font-medium">LAST SESSION</th>
                    <th class="p-4 font-medium">PARTY GOALS</th>
                    <th class="p-4 font-medium">TARGET NOTE</th>
                    <th class="p-4 font-medium" />
                  </tr>
                </thead>
                <tbody class="divide-y divide-theme-border/50">
                  <For each={rows}>
                    {(row) => (
                      <tr class="hover:bg-theme-hover transition-colors group">
                        <td class="p-4 font-medium text-theme-text-primary">{row.name}</td>
                        <td class="p-4 text-theme-text-secondary">{row.des}</td>
                        <td class="p-4">
                          <div class="flex gap-1.5 text-xs font-medium">
                            <For each={row.pal}>
                              {(p) => (
                                <span class={`w-5 h-5 flex items-center justify-center rounded-[var(--radius-sm)] ${filterBadgeClass(p)}`}>
                                  {p}
                                </span>
                              )}
                            </For>
                          </div>
                        </td>
                        <td class="p-4 text-right tabular-nums text-theme-text-primary">{row.time}</td>
                        <td class="p-4 text-theme-accent/80">{row.date}</td>
                        <td class="p-4 text-theme-text-secondary">{row.goal}</td>
                        <td class="p-4 text-theme-text-secondary truncate max-w-[200px]">{row.note}</td>
                        <td class="p-4 text-right">
                          <button class="text-theme-text-tertiary hover:text-theme-text-primary transition-colors opacity-0 group-hover:opacity-100 flex items-center gap-1 text-xs">
                            Expand <Maximize2 class="w-3 h-3" />
                          </button>
                        </td>
                      </tr>
                    )}
                  </For>
                </tbody>
              </table>
            </div>
          </GlassPanel>
        </div>
      </div>
    </div>
  );
}
