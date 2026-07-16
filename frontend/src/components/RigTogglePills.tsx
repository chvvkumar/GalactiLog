import { For } from "solid-js";
import Toggle from "./ui/Toggle";

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
            <Toggle
              active={isActive()}
              color={color()}
              onClick={() => props.onToggle(rig)}
            >
              {rig}
            </Toggle>
          );
        }}
      </For>
    </div>
  );
}
