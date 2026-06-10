import { Component, createSignal } from "solid-js";
import Dialog from "../Dialog";
import TargetCreateForm, { TargetFormValues } from "./TargetCreateForm";
import { api } from "../../api/client";
import { showToast } from "../Toast";
import { getErrorMessage } from "../../utils/errors";

interface Props {
  onClose: () => void;
  onCreated: () => void;
}

const CreateTargetModal: Component<Props> = (props) => {
  const [submitting, setSubmitting] = createSignal(false);

  const handleSubmit = async (values: TargetFormValues) => {
    setSubmitting(true);
    try {
      const res = await api.createCustomTarget(values);
      const linked = res.linked_images > 0
        ? ` and linked ${res.linked_images} existing images`
        : "";
      showToast(`Created target "${values.primary_name}"${linked}`);
      props.onCreated();
    } catch (e: unknown) {
      showToast(getErrorMessage(e, "Failed to create target"), "error");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Dialog open aria-labelledby="create-target-title" onClose={props.onClose}>
      <div
        class="bg-theme-surface border border-theme-border rounded-[var(--radius-md)] shadow-[var(--shadow-lg)] max-w-lg w-full mx-4 max-h-[80vh] overflow-y-auto"
        onClick={(e) => e.stopPropagation()}
      >
        <div class="p-4 border-b border-theme-border">
          <h3 id="create-target-title" class="text-theme-text-primary font-medium">Create Target</h3>
          <p class="text-xs text-theme-text-secondary mt-1">
            Manually add a target. Use for planets, comets, and other objects catalogs cannot resolve, or to pre-create a target before its images are scanned.
          </p>
        </div>
        <div class="p-4">
          <TargetCreateForm
            initial={{ user_defined: true }}
            submitLabel={submitting() ? "Creating..." : "Create Target"}
            submitting={submitting()}
            onSubmit={handleSubmit}
            onCancel={props.onClose}
          />
        </div>
      </div>
    </Dialog>
  );
};

export default CreateTargetModal;
