import { Component, Show, createSignal, onMount } from "solid-js";
import { api } from "../../api/client";
import { useAuth } from "../AuthProvider";
import type { MergeCandidateResponse } from "../../types";
import DuplicatesSection from "./DuplicatesSection";
import UnresolvedSection from "./UnresolvedSection";
import MergeHistorySection from "./MergeHistorySection";
import MaintenanceSection from "./MaintenanceSection";

interface ScanSummary {
  completed_at: string;
  files_ingested: number;
  targets_created: number;
  targets_updated: number;
  duplicates_found: number;
  unresolved_names: number;
  errors: number;
}

export const TargetManagementTab: Component = () => {
  const { isAdmin } = useAuth();

  const [pending, setPending] = createSignal<MergeCandidateResponse[]>([]);
  const [accepted, setAccepted] = createSignal<MergeCandidateResponse[]>([]);
  const [scanSummary, setScanSummary] = createSignal<ScanSummary | null>(null);

  const refresh = async () => {
    try {
      const [p, a] = await Promise.all([
        api.getMergeCandidates("pending"),
        api.getMergeCandidates("accepted"),
      ]);
      setPending(p);
      setAccepted(a);
    } catch {
      // non-blocking
    }
  };

  onMount(async () => {
    refresh();
    try {
      const s = await api.getScanSummary();
      if (s) setScanSummary(s as ScanSummary);
    } catch {
      // non-blocking
    }
  });

  const duplicates = () => pending().filter((c) => c.method !== "orphan");
  const unresolved = () => pending().filter((c) => c.method === "orphan");

  return (
    <div class="space-y-4">

      {/* Post-scan summary banner */}
      <Show when={scanSummary()}>
        {(s) => (
          <div class="bg-theme-surface border border-theme-border rounded-[var(--radius-md)] shadow-[var(--shadow-sm)] p-4">
            <p class="text-xs text-theme-text-secondary mb-2 uppercase tracking-wide font-medium">Last Scan</p>
            <div class="flex flex-wrap gap-4">
              <div class="text-sm">
                <span class="text-theme-text-secondary">Files ingested: </span>
                <span class="text-theme-text-primary font-medium">{s().files_ingested}</span>
              </div>
              <Show when={s().targets_created > 0 || s().targets_updated > 0}>
                <div class="text-sm">
                  <span class="text-theme-text-secondary">New targets: </span>
                  <span class="text-green-400 font-medium">{s().targets_created}</span>
                </div>
              </Show>
              <Show when={s().duplicates_found > 0}>
                <div class="text-sm">
                  <span class="text-theme-text-secondary">Duplicates: </span>
                  <span class="text-yellow-400 font-medium">{s().duplicates_found}</span>
                </div>
              </Show>
              <Show when={s().unresolved_names > 0}>
                <div class="text-sm">
                  <span class="text-theme-text-secondary">Unresolved: </span>
                  <span class="text-blue-400 font-medium">{s().unresolved_names}</span>
                </div>
              </Show>
              <Show when={s().errors > 0}>
                <div class="text-sm">
                  <span class="text-theme-text-secondary">Errors: </span>
                  <span class="text-red-400 font-medium">{s().errors}</span>
                </div>
              </Show>
            </div>
          </div>
        )}
      </Show>

      {/* Retry banner for unresolved items */}
      <Show when={isAdmin() && unresolved().length > 0}>
        <div class="flex items-center justify-between gap-3 px-4 py-3 bg-blue-500/10 border border-blue-500/20 rounded-[var(--radius-md)]">
          <p class="text-sm text-blue-400">
            {unresolved().length} {unresolved().length === 1 ? "target name" : "target names"} could not be resolved.
          </p>
        </div>
      </Show>

      {/* Duplicates section */}
      <DuplicatesSection candidates={duplicates} onAction={refresh} />

      {/* Unresolved Names section */}
      <UnresolvedSection candidates={unresolved} onAction={refresh} />

      {/* Merge History section */}
      <MergeHistorySection candidates={accepted} onAction={refresh} />

      {/* Maintenance section */}
      <MaintenanceSection onMaintenanceComplete={refresh} />
    </div>
  );
};
