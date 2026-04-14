import { createSignal, Show } from "solid-js";
import { FilePreviewModal } from "./FilePreviewModal";

type Props = {
  imageId: string;
  filePath: string;
  thumbnailUrl?: string | null;
  display?: string;
  class?: string;
};

export function ClickableFilePath(props: Props) {
  const [open, setOpen] = createSignal(false);
  const label = () => props.display ?? props.filePath;

  return (
    <>
      <button
        class={`text-blue-400 hover:text-blue-300 hover:underline cursor-pointer truncate ${props.class ?? ""}`}
        onClick={() => setOpen(true)}
        title={props.filePath}
      >
        {label()}
      </button>
      <Show when={open()}>
        <FilePreviewModal
          imageId={props.imageId}
          filePath={props.filePath}
          thumbnailUrl={props.thumbnailUrl}
          onClose={() => setOpen(false)}
        />
      </Show>
    </>
  );
}
