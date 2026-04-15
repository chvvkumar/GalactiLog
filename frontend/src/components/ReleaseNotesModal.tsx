import { Component, Show } from "solid-js";
import { Portal } from "solid-js/web";

interface LatestRelease {
  available: boolean;
  running: string;
  is_newer?: boolean;
  tag?: string;
  name?: string;
  url?: string;
  published_at?: string;
  body?: string;
  error?: string;
}

function escapeHtml(s: string): string {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

// Minimal markdown renderer for GitHub release bodies.
// Handles: headings (##, ###), unordered lists, bold, inline code, links,
// horizontal rules, code fences, paragraphs.
function renderMarkdown(md: string): string {
  const lines = md.replace(/\r\n/g, "\n").split("\n");
  const out: string[] = [];
  let inList = false;
  let inCode = false;
  let codeBuf: string[] = [];
  let paraBuf: string[] = [];

  const flushPara = () => {
    if (paraBuf.length) {
      out.push(`<p>${inlineFmt(paraBuf.join(" "))}</p>`);
      paraBuf = [];
    }
  };
  const closeList = () => {
    if (inList) {
      out.push("</ul>");
      inList = false;
    }
  };

  const inlineFmt = (text: string): string => {
    let s = escapeHtml(text);
    // inline code
    s = s.replace(/`([^`]+)`/g, "<code>$1</code>");
    // bold
    s = s.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
    // links
    s = s.replace(
      /\[([^\]]+)\]\(([^)]+)\)/g,
      '<a href="$2" target="_blank" rel="noopener noreferrer" class="text-theme-info hover:underline">$1</a>',
    );
    return s;
  };

  for (const rawLine of lines) {
    const line = rawLine;

    if (line.trim().startsWith("```")) {
      if (inCode) {
        out.push(`<pre class="bg-theme-elevated rounded p-2 text-xs overflow-x-auto"><code>${escapeHtml(codeBuf.join("\n"))}</code></pre>`);
        codeBuf = [];
        inCode = false;
      } else {
        flushPara();
        closeList();
        inCode = true;
      }
      continue;
    }
    if (inCode) {
      codeBuf.push(line);
      continue;
    }

    if (!line.trim()) {
      flushPara();
      closeList();
      continue;
    }

    // Headings
    const h = line.match(/^(#{1,6})\s+(.*)$/);
    if (h) {
      flushPara();
      closeList();
      const level = Math.min(h[1].length + 1, 6); // bump ## to h3 so modal h2 dominates
      out.push(`<h${level} class="font-semibold text-theme-text-primary mt-3 mb-1">${inlineFmt(h[2])}</h${level}>`);
      continue;
    }

    // Horizontal rule
    if (/^---+\s*$/.test(line)) {
      flushPara();
      closeList();
      out.push('<hr class="my-3 border-theme-border" />');
      continue;
    }

    // Bullet
    const b = line.match(/^\s*[-*]\s+(.*)$/);
    if (b) {
      flushPara();
      if (!inList) {
        out.push('<ul class="list-disc list-inside space-y-0.5 my-2">');
        inList = true;
      }
      out.push(`<li>${inlineFmt(b[1])}</li>`);
      continue;
    }

    closeList();
    paraBuf.push(line.trim());
  }

  flushPara();
  closeList();
  if (inCode && codeBuf.length) {
    out.push(`<pre class="bg-theme-elevated rounded p-2 text-xs overflow-x-auto"><code>${escapeHtml(codeBuf.join("\n"))}</code></pre>`);
  }

  return out.join("\n");
}

function formatDate(iso?: string): string {
  if (!iso) return "";
  try {
    return new Date(iso).toLocaleDateString(undefined, {
      year: "numeric",
      month: "short",
      day: "numeric",
    });
  } catch {
    return iso;
  }
}

const ReleaseNotesModal: Component<{
  release: LatestRelease;
  onClose: () => void;
}> = (props) => {
  return (
    <Portal>
      <div
        class="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm p-4"
        onClick={props.onClose}
      >
        <div
          class="relative max-h-[85vh] w-full max-w-2xl overflow-y-auto rounded-[var(--radius-md)] bg-theme-surface border border-theme-border shadow-[var(--shadow-lg)]"
          onClick={(e) => e.stopPropagation()}
        >
          <div class="sticky top-0 bg-theme-surface border-b border-theme-border px-5 py-3 flex items-start justify-between gap-4">
            <div>
              <h2 class="text-lg font-semibold text-theme-text-primary">
                {props.release.name || props.release.tag || "Latest release"}
              </h2>
              <Show when={props.release.tag || props.release.published_at}>
                <div class="text-xs text-theme-text-secondary mt-0.5">
                  <Show when={props.release.tag}>{props.release.tag}</Show>
                  <Show when={props.release.tag && props.release.published_at}>{" "}&middot;{" "}</Show>
                  <Show when={props.release.published_at}>{formatDate(props.release.published_at)}</Show>
                </div>
              </Show>
              <Show when={props.release.is_newer}>
                <div class="text-xs text-theme-warning mt-1">
                  A newer release is available. Running {props.release.running}.
                </div>
              </Show>
            </div>
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
          <div
            class="px-5 py-4 text-sm text-theme-text-primary leading-relaxed"
            innerHTML={renderMarkdown(props.release.body || "_No release notes provided._")}
          />
          <Show when={props.release.url}>
            <div class="px-5 pb-4">
              <a
                href={props.release.url}
                target="_blank"
                rel="noopener noreferrer"
                class="text-xs text-theme-text-secondary hover:text-theme-text-primary underline"
              >
                View on GitHub
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
