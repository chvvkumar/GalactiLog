import { For } from "solid-js";

/** A small palette of distinguishable rig colors. */
const RIG_COLORS = [
  "#60a5fa", // blue
  "#f59e0b", // amber
  "#34d399", // emerald
  "#f472b6", // pink
  "#a78bfa", // violet
  "#fb923c", // orange
];

export function rigColor(index: number): string {
  return RIG_COLORS[index % RIG_COLORS.length];
}

interface Props {
  rigs: string[];
  enabledRigs: string[];
  onToggle: (rig: string) => void;
}

export default function RigTogglePills(props: Props) {
  return (
    <div class="flex flex-wrap gap-1.5">
      <For each={props.rigs}>
        {(rig, index) => {
          const isActive = () => props.enabledRigs.includes(rig);
          const color = () => rigColor(index());
          return (
            <button
              class="px-2 py-0.5 rounded text-caption font-medium border transition-colors cursor-pointer"
              style={{
                "border-color": isActive() ? color() : "var(--color-border-default)",
                "background-color": isActive() ? `${color()}22` : "var(--color-bg-elevated)",
                color: isActive() ? color() : "var(--color-text-tertiary)",
              }}
              onClick={() => props.onToggle(rig)}
            >
              {rig}
            </button>
          );
        }}
      </For>
    </div>
  );
}
