import { createSignal, type Component } from "solid-js";

interface InlineRenameProps {
  initialValue: string;
  onSave: (value: string) => void;
  onCancel: () => void;
  saving: boolean;
  inputClass: string;
  // Size/leading classes shared by the save and cancel icon buttons, e.g. "text-lg leading-none".
  iconSizeClass?: string;
  // Hover color for the cancel button; pages differ here (theme-error vs theme-danger).
  cancelHoverClass?: string;
}

// Inline rename text editor: an input plus save/cancel controls, submitted on
// Enter and dismissed on Escape. Used for the target and mosaic title editors.
const InlineRename: Component<InlineRenameProps> = (props) => {
  const [value, setValue] = createSignal(props.initialValue);
  const iconClass = () => props.iconSizeClass ?? "text-lg leading-none";
  const cancelHover = () => props.cancelHoverClass ?? "hover:text-theme-error";

  return (
    <>
      <input
        type="text"
        class={props.inputClass}
        value={value()}
        onInput={(e) => setValue(e.currentTarget.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter") props.onSave(value());
          if (e.key === "Escape") props.onCancel();
        }}
        ref={(el) => { setTimeout(() => el?.focus(), 0); }}
        disabled={props.saving}
      />
      <button
        class={`text-theme-text-tertiary hover:text-green-400 transition-colors ${iconClass()}`}
        title="Save"
        aria-label="Save name"
        onClick={() => props.onSave(value())}
        disabled={props.saving}
      >
        &#10003;
      </button>
      <button
        class={`text-theme-text-tertiary ${cancelHover()} transition-colors ${iconClass()}`}
        title="Cancel"
        aria-label="Cancel rename"
        onClick={props.onCancel}
        disabled={props.saving}
      >
        &#10005;
      </button>
    </>
  );
};

export default InlineRename;
