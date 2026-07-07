import { Component, Show, createSignal, onMount } from "solid-js";
import { apiClient } from "../../api/generated/client";
import { unwrap } from "../../api/unwrap";
import { showToast } from "../Toast";
import type { MergeCandidateResponse, OrphanPreviewResponse } from "../../api/types";
import Dialog from "../Dialog";
import TargetCreateForm, { TargetFormValues } from "./TargetCreateForm";
import { getErrorMessage } from "../../utils/errors";

interface Props {
  candidate: MergeCandidateResponse;
  onClose: () => void;
  onResolved: () => void;
}

const CreateTargetFromOrphanModal: Component<Props> = (props) => {
  const [preview, setPreview] = createSignal<OrphanPreviewResponse | null>(null);
  const [loadingPreview, setLoadingPreview] = createSignal(true);
  const [creating, setCreating] = createSignal(false);

  onMount(async () => {
    try {
      const res = await apiClient
        .POST("/api/targets/orphan-preview", { body: { source_name: props.candidate.source_name } })
        .then(unwrap);
      setPreview(res);
    } catch {
      showToast("Failed to load preview", "error");
    } finally {
      setLoadingPreview(false);
    }
  });

  const handleCreate = async (values: TargetFormValues) => {
    setCreating(true);
    try {
      await apiClient
        .POST("/api/targets/orphan-create", {
          body: { candidate_id: props.candidate.id, ...values },
        })
        .then(unwrap);
      showToast(`Created target "${values.primary_name}"`);
      props.onResolved();
    } catch (e: unknown) {
      showToast(getErrorMessage(e, "Failed to create target"), "error");
    } finally {
      setCreating(false);
    }
  };

  return (
    <Dialog open aria-labelledby="create-orphan-title" onClose={props.onClose}>
      <div
        class="bg-theme-surface border border-theme-border rounded-[var(--radius-md)] shadow-[var(--shadow-lg)] max-w-lg w-full mx-4 max-h-[80vh] overflow-y-auto"
        onClick={(e) => e.stopPropagation()}
      >
        <div class="p-4 border-b border-theme-border">
          <h3 id="create-orphan-title" class="text-theme-text-primary font-medium">
            Create target from "{props.candidate.source_name}"
          </h3>
          <p class="text-xs text-theme-text-secondary mt-1">
            {props.candidate.source_image_count} images will be linked to the new target
          </p>
        </div>

        <div class="p-4">
          <Show when={!loadingPreview()} fallback={
            <div class="text-sm text-theme-text-secondary py-4 text-center">Querying SIMBAD...</div>
          }>
            <Show when={preview()}>
              {(p) => (
                <div class="space-y-3">
                  <div class={`text-xs px-2 py-1 rounded ${
                    p().resolved
                      ? "bg-green-500/10 text-green-400 border border-green-500/20"
                      : "bg-theme-warning/10 text-theme-warning border border-theme-warning/20"
                  }`}>
                    {p().resolved
                      ? `SIMBAD resolved as: ${p().primary_name}`
                      : "No catalog match, coordinates from FITS headers"}
                  </div>

                  <TargetCreateForm
                    initial={{
                      primary_name: p().primary_name,
                      ra: p().ra,
                      dec: p().dec,
                      object_type: p().object_type,
                      catalog_id: p().catalog_id,
                      user_defined: !p().resolved,
                    }}
                    submitLabel={creating() ? "Creating..." : "Create Target"}
                    submitting={creating()}
                    onSubmit={handleCreate}
                    onCancel={props.onClose}
                  />
                </div>
              )}
            </Show>
          </Show>
        </div>
      </div>
    </Dialog>
  );
};

export default CreateTargetFromOrphanModal;
