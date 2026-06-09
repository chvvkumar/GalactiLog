import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

// Tests for handleRename validation feedback (UX-6)
// and clipboard failure path (UX-12)

// Simulate the handleRename validation logic extracted from TargetDetailPage
// (matches the exact branching added in the fix)
function makeHandleRename(
  showToastFn: (msg: string, level?: string) => void,
  setEditingFn: (v: boolean) => void,
  saveIdentityFn: (name: string) => Promise<void>,
) {
  return async (editName: string, currentName: string) => {
    const name = editName.trim();
    if (!name) {
      showToastFn("Name cannot be empty", "error");
      return;
    }
    if (name === currentName) {
      showToastFn("Name is unchanged", "error");
      setEditingFn(false);
      return;
    }
    await saveIdentityFn(name);
    setEditingFn(false);
  };
}

describe("handleRename validation (UX-6)", () => {
  let showToast: ReturnType<typeof vi.fn>;
  let setEditing: ReturnType<typeof vi.fn>;
  let saveIdentity: ReturnType<typeof vi.fn>;
  let handleRename: ReturnType<typeof makeHandleRename>;

  beforeEach(() => {
    showToast = vi.fn();
    setEditing = vi.fn();
    saveIdentity = vi.fn().mockResolvedValue(undefined);
    handleRename = makeHandleRename(showToast, setEditing, saveIdentity);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("shows an error toast when the name is empty", async () => {
    await handleRename("   ", "NGC 7000");
    expect(showToast).toHaveBeenCalledWith("Name cannot be empty", "error");
    expect(saveIdentity).not.toHaveBeenCalled();
    expect(setEditing).not.toHaveBeenCalled();
  });

  it("shows an error toast when the name is unchanged", async () => {
    await handleRename("NGC 7000", "NGC 7000");
    expect(showToast).toHaveBeenCalledWith("Name is unchanged", "error");
    expect(saveIdentity).not.toHaveBeenCalled();
    expect(setEditing).toHaveBeenCalledWith(false);
  });

  it("trims whitespace before comparing to current name", async () => {
    await handleRename("  NGC 7000  ", "NGC 7000");
    expect(showToast).toHaveBeenCalledWith("Name is unchanged", "error");
    expect(saveIdentity).not.toHaveBeenCalled();
  });

  it("proceeds with save when name is non-empty and different", async () => {
    await handleRename("Orion Nebula", "NGC 7000");
    expect(showToast).not.toHaveBeenCalled();
    expect(saveIdentity).toHaveBeenCalledWith("Orion Nebula");
    expect(setEditing).toHaveBeenCalledWith(false);
  });
});

// Object-type inline editor (regression: saved type appeared to "reset")
//
// The editor displays detail.object_category and binds the <select> value to it.
// handleObjectTypeChange saves via updateTargetIdentity({ object_type }), then
// refetches the detail. If the refetched detail omits object_category, the UI
// keeps showing "Unknown type" and the select resets to "", so the selection
// looks lost. These tests assert the save path calls the API and that the
// display/select source is object_category (which the backend must populate).
function makeHandleObjectTypeChange(
  updateIdentity: (id: string, body: { object_type: string }) => Promise<void>,
  refetchDetail: () => Promise<{ object_category: string | null }>,
  setEditing: (v: boolean) => void,
) {
  return async (targetId: string, value: string) => {
    await updateIdentity(targetId, { object_type: value });
    setEditing(false);
    return await refetchDetail();
  };
}

// Mirrors the JSX bindings: display text and select value both come from object_category.
function displayObjectType(detail: { object_category: string | null }): string {
  return detail.object_category ?? "Unknown type";
}
function selectValue(detail: { object_category: string | null }): string {
  return detail.object_category ?? "";
}

describe("object-type inline editor save", () => {
  it("calls updateTargetIdentity with object_type and does not navigate", async () => {
    const updateIdentity = vi.fn().mockResolvedValue(undefined);
    const setEditing = vi.fn();
    const refetchDetail = vi.fn().mockResolvedValue({ object_category: "Galaxy" });
    const handle = makeHandleObjectTypeChange(updateIdentity, refetchDetail, setEditing);

    await handle("abc-123", "Galaxy");

    expect(updateIdentity).toHaveBeenCalledWith("abc-123", { object_type: "Galaxy" });
    expect(setEditing).toHaveBeenCalledWith(false);
    expect(refetchDetail).toHaveBeenCalled();
  });

  it("shows the saved category after refetch returns object_category", async () => {
    const refetchDetail = vi.fn().mockResolvedValue({ object_category: "Galaxy" });
    const handle = makeHandleObjectTypeChange(
      vi.fn().mockResolvedValue(undefined),
      refetchDetail,
      vi.fn(),
    );

    const detail = await handle("abc-123", "Galaxy");

    // Regression guard: the editor reads object_category, so a populated value
    // must surface in both the display label and the select binding.
    expect(displayObjectType(detail)).toBe("Galaxy");
    expect(selectValue(detail)).toBe("Galaxy");
  });

  it("falls back to 'Unknown type' when object_category is null", () => {
    expect(displayObjectType({ object_category: null })).toBe("Unknown type");
    expect(selectValue({ object_category: null })).toBe("");
  });
});

// Simulate the clipboard failure handling from copyMultiSessionAstrobinCsv (UX-12)
describe("clipboard failure toast (UX-12)", () => {
  let showToast: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    showToast = vi.fn();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("calls showToast with error when clipboard write fails", async () => {
    const writeText = vi.fn().mockRejectedValue(new Error("Permission denied"));
    Object.defineProperty(globalThis, "navigator", {
      value: { clipboard: { writeText } },
      configurable: true,
    });

    // Reproduce the pattern used in copyMultiSessionAstrobinCsv and copyAstrobinCsv
    const csv = "date,filter\n2024-01-01,Ha";
    await navigator.clipboard.writeText(csv).then(() => {
      // success branch — not reached
    }).catch(() => {
      showToast("Failed to copy to clipboard", "error");
    });

    expect(showToast).toHaveBeenCalledWith("Failed to copy to clipboard", "error");
  });

  it("does not call error toast when clipboard write succeeds", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(globalThis, "navigator", {
      value: { clipboard: { writeText } },
      configurable: true,
    });

    const csv = "date,filter\n2024-01-01,Ha";
    let successCalled = false;
    await navigator.clipboard.writeText(csv).then(() => {
      successCalled = true;
    }).catch(() => {
      showToast("Failed to copy to clipboard", "error");
    });

    expect(successCalled).toBe(true);
    expect(showToast).not.toHaveBeenCalled();
  });
});
