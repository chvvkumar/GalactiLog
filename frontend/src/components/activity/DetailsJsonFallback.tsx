import { Component } from "solid-js";

const DetailsJsonFallback: Component<{ details: Record<string, unknown> }> = (props) => {
  const formatted = () => {
    try {
      return JSON.stringify(props.details, null, 2);
    } catch {
      return String(props.details);
    }
  };

  return (
    <pre class="text-xs text-theme-text-secondary bg-theme-base/50 border border-theme-border rounded p-2 overflow-x-auto max-h-40 font-mono whitespace-pre-wrap break-all">
      {formatted()}
    </pre>
  );
};

export default DetailsJsonFallback;
