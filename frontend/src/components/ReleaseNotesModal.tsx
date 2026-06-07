import { Component, Show } from "solid-js";
import { Portal } from "solid-js/web";

interface LatestRelease {
  available: boolean;
  running: string;
  running_sha?: string;
  is_newer?: boolean;
  tag?: string;
  remote_sha?: string | null;
  published_at?: string | null;
  compare_url?: string | null;
  source?: string;
  error?: string;
}

function shortSha(sha?: string | null): string {
  if (!sha) return "";
  return sha.slice(0, 7);
}

function formatDateTime(iso?: string | null): string {
  if (!iso) return "";
  try {
    return new Date(iso).toLocaleString(undefined, {
      year: "numeric",
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return iso;
  }
}

const ReleaseNotesModal: Component<{
  release: LatestRelease;
  onClose: () => void;
}> = (props) => {
  const runningShort = () => shortSha(props.release.running_sha) || props.release.running;
  const remoteShort = () => shortSha(props.release.remote_sha);

  return (
    <Portal>
      <div
        class="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm p-4"
        onClick={props.onClose}
      >
        <div
          class="modal-surface relative max-h-[85vh] w-full max-w-md overflow-y-auto rounded-[var(--radius-md)] border border-theme-border shadow-[var(--shadow-lg)]"
          onClick={(e) => e.stopPropagation()}
        >
          <div class="modal-surface sticky top-0 border-b border-theme-border px-5 py-3 flex items-start justify-between gap-4">
            <h2 class="text-lg font-semibold text-theme-text-primary">
              A newer build is available
            </h2>
            <button
              onClick={props.onClose}
              class="text-theme-text-secondary hover:text-theme-text-primary transition-colors"
              aria-label="Close"
            >
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <line x1="18" y1="6" x2="6" y2="18" />
                <line x1="6" y1="6" x2="18" y2="18" />
              </svg>
            </button>
          </div>

          <div class="px-5 py-4 text-sm text-theme-text-primary leading-relaxed space-y-3">
            <Show
              when={remoteShort()}
              fallback={
                <p class="text-theme-text-secondary">
                  A newer build is available. Running {runningShort()}.
                </p>
              }
            >
              <div class="flex items-center gap-2 font-mono text-xs">
                <span class="rounded bg-theme-elevated px-2 py-1 text-theme-text-secondary">
                  {runningShort()}
                </span>
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="text-theme-text-secondary">
                  <line x1="5" y1="12" x2="19" y2="12" />
                  <polyline points="12 5 19 12 12 19" />
                </svg>
                <span class="rounded bg-theme-warning/15 px-2 py-1 text-theme-warning">
                  {remoteShort()}
                </span>
              </div>
            </Show>

            <Show when={props.release.published_at}>
              <p class="text-xs text-theme-text-secondary">
                Published {formatDateTime(props.release.published_at)}
              </p>
            </Show>

            <Show when={props.release.tag}>
              <p class="text-xs text-theme-text-secondary">
                Tag: {props.release.tag}
              </p>
            </Show>
          </div>

          <Show
            when={props.release.compare_url}
            fallback={
              <div class="px-5 pb-4">
                <span class="text-xs text-theme-text-secondary">
                  Compare details are unavailable for this build.
                </span>
              </div>
            }
          >
            <div class="px-5 pb-4">
              <a
                href={props.release.compare_url!}
                target="_blank"
                rel="noopener noreferrer"
                class="text-xs text-theme-text-secondary hover:text-theme-text-primary underline"
              >
                View changes on GitHub
              </a>
            </div>
          </Show>
        </div>
      </div>
    </Portal>
  );
};

export default ReleaseNotesModal;
export type { LatestRelease };
