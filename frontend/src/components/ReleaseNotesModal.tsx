import { Component, Show } from "solid-js";
import Dialog from "./Dialog";

interface ReleaseInfo {
  tag: string;
  name: string | null;
  url: string;
  body: string;
  published_at: string | null;
}

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
  release?: ReleaseInfo | null;
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

function escapeHtml(text: string): string {
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

// Minimal, XSS-safe markdown renderer. The raw text is HTML-escaped first,
// then a small subset of markdown is converted to HTML. No raw HTML from the
// source survives, so user/release content cannot inject markup.
function renderMarkdown(raw: string): string {
  const lines = escapeHtml(raw ?? "").split(/\r?\n/);
  const html: string[] = [];

  let inCodeBlock = false;
  let codeBuffer: string[] = [];
  let listType: "ul" | "ol" | null = null;

  const closeList = () => {
    if (listType) {
      html.push(`</${listType}>`);
      listType = null;
    }
  };

  const inline = (text: string): string => {
    // Inline code first so its contents are not further processed.
    let out = text.replace(/`([^`]+)`/g, '<code class="rounded bg-theme-elevated px-1 py-0.5 text-xs">$1</code>');
    // Links: [label](url) -- only allow http(s) and mailto schemes.
    out = out.replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, (m, label, url) => {
      if (/^(https?:\/\/|mailto:)/i.test(url)) {
        return `<a href="${url}" target="_blank" rel="noopener noreferrer" class="text-theme-accent underline hover:text-theme-text-primary">${label}</a>`;
      }
      return m;
    });
    // Bold then italics.
    out = out.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
    out = out.replace(/__([^_]+)__/g, "<strong>$1</strong>");
    out = out.replace(/\*([^*]+)\*/g, "<em>$1</em>");
    out = out.replace(/_([^_]+)_/g, "<em>$1</em>");
    return out;
  };

  for (const line of lines) {
    const fence = line.match(/^```/);
    if (fence) {
      if (inCodeBlock) {
        html.push(
          `<pre class="overflow-x-auto rounded bg-theme-elevated p-2 text-xs"><code>${codeBuffer.join("\n")}</code></pre>`,
        );
        codeBuffer = [];
        inCodeBlock = false;
      } else {
        closeList();
        inCodeBlock = true;
      }
      continue;
    }

    if (inCodeBlock) {
      codeBuffer.push(line);
      continue;
    }

    const heading = line.match(/^(#{1,6})\s+(.*)$/);
    if (heading) {
      closeList();
      const level = Math.min(heading[1].length, 6);
      const sizes: Record<number, string> = {
        1: "text-base font-semibold",
        2: "text-base font-semibold",
        3: "text-sm font-semibold",
        4: "text-sm font-semibold",
        5: "text-sm font-medium",
        6: "text-sm font-medium",
      };
      html.push(`<h${level} class="${sizes[level]} mt-3 mb-1">${inline(heading[2])}</h${level}>`);
      continue;
    }

    const ulItem = line.match(/^\s*[-*+]\s+(.*)$/);
    const olItem = line.match(/^\s*\d+\.\s+(.*)$/);
    if (ulItem) {
      if (listType !== "ul") {
        closeList();
        html.push('<ul class="list-disc pl-5 space-y-0.5">');
        listType = "ul";
      }
      html.push(`<li>${inline(ulItem[1])}</li>`);
      continue;
    }
    if (olItem) {
      if (listType !== "ol") {
        closeList();
        html.push('<ol class="list-decimal pl-5 space-y-0.5">');
        listType = "ol";
      }
      html.push(`<li>${inline(olItem[1])}</li>`);
      continue;
    }

    if (line.trim() === "") {
      closeList();
      continue;
    }

    closeList();
    html.push(`<p>${inline(line)}</p>`);
  }

  if (inCodeBlock) {
    html.push(
      `<pre class="overflow-x-auto rounded bg-theme-elevated p-2 text-xs"><code>${codeBuffer.join("\n")}</code></pre>`,
    );
  }
  closeList();

  return html.join("\n");
}

const ReleaseNotesModal: Component<{
  release: LatestRelease;
  onClose: () => void;
}> = (props) => {
  const runningShort = () => shortSha(props.release.running_sha) || props.release.running;
  const remoteShort = () => shortSha(props.release.remote_sha);
  const rel = () => props.release.release;

  return (
    <Dialog
      open
      aria-labelledby="release-notes-title"
      class="bg-black/80 backdrop-blur-sm p-4"
      onClose={props.onClose}
    >
      <div
        class="modal-surface relative max-h-[85vh] w-full max-w-2xl overflow-y-auto rounded-[var(--radius-md)] border border-theme-border shadow-[var(--shadow-lg)]"
        onClick={(e) => e.stopPropagation()}
      >
          <div class="modal-surface sticky top-0 border-b border-theme-border px-5 py-3 flex items-start justify-between gap-4">
            <h2 id="release-notes-title" class="text-lg font-semibold text-theme-text-primary">
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

          <Show
            when={rel()}
            fallback={
              <>
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
              </>
            }
          >
            <div class="px-5 py-4 text-sm text-theme-text-primary leading-relaxed space-y-3">
              <div class="space-y-0.5">
                <p class="text-base font-semibold text-theme-text-primary">
                  {rel()!.name || rel()!.tag}
                </p>
                <p class="text-xs text-theme-text-secondary">
                  Tag: {rel()!.tag}
                </p>
                <Show when={rel()!.published_at}>
                  <p class="text-xs text-theme-text-secondary">
                    Published {formatDateTime(rel()!.published_at)}
                  </p>
                </Show>
              </div>

              <Show
                when={rel()!.body && rel()!.body.trim()}
                fallback={
                  <p class="text-xs text-theme-text-secondary">
                    No release notes provided.
                  </p>
                }
              >
                <div
                  class="markdown-body space-y-2 text-sm text-theme-text-primary"
                  // eslint-disable-next-line solid/no-innerhtml
                  innerHTML={renderMarkdown(rel()!.body)}
                />
              </Show>
            </div>

            <div class="px-5 pb-4">
              <a
                href={rel()!.url}
                target="_blank"
                rel="noopener noreferrer"
                class="text-xs text-theme-text-secondary hover:text-theme-text-primary underline"
              >
                View on GitHub
              </a>
            </div>
          </Show>
        </div>
    </Dialog>
  );
};

export default ReleaseNotesModal;
export type { LatestRelease };
