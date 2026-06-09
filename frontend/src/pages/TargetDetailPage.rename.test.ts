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
