import { describe, it, expect, vi } from "vitest";
import { render, fireEvent } from "@solidjs/testing-library";
import WbppLevelEditor from "./WbppLevelEditor";
import type { WbppSessionPreview, WbppFolderLevel } from "../../api/types";

const level = (path: string, extra: Partial<WbppFolderLevel> = {}): WbppFolderLevel => ({
  container_path: path,
  depth_from_root: path.split("/").length,
  frame_bytes: null,
  frame_count: 10,
  is_contaminated: false,
  path,
  relative_path: path,
  ...extra,
});

const session = (overrides: Partial<WbppSessionPreview> = {}): WbppSessionPreview => ({
  default_level_index: 1,
  excluded_frame_count: 0,
  session_date: "2026-03-04",
  total_frame_count: 30,
  levels: [
    level("/lib/M31"),
    level("/lib/M31/2026-03-04"),
    level("/lib/M31/2026-03-04/LIGHT"),
  ],
  ...overrides,
});

const contaminated = () =>
  session({
    default_level_index: 2,
    levels: [
      level("/lib/M31", {
        is_contaminated: true,
        other_targets: ["M33", "NGC 7000"],
        other_dates: ["2026-03-01"],
      }),
      level("/lib/M31/2026-03-04"),
      level("/lib/M31/2026-03-04/LIGHT"),
    ],
  });

describe("WbppLevelEditor", () => {
  // The editor does not recommend a level. The parent still seeds the selection
  // from default_level_index, but that stays a starting point rather than advice
  // the rows argue for.
  it("does not badge the default level as recommended", () => {
    const { container } = render(() => (
      <WbppLevelEditor session={session()} chosenIndex={1} onSelect={() => {}} libraryRoot="/lib" separator="/" />
    ));
    expect(container.textContent).not.toContain("Recommended");
  });

  it("quantifies contamination instead of a bare '!'", () => {
    const { container } = render(() => (
      <WbppLevelEditor
        session={contaminated()}
        chosenIndex={2}
        onSelect={() => {}}
        libraryRoot="/lib"
        separator="/"
      />
    ));
    const row = container.querySelectorAll("label")[0];
    expect(row.textContent).toContain("+2 other targets");
    expect(row.textContent).toContain("+1 other session");
    expect(row.textContent).not.toContain("!");
  });

  it("keeps the contaminating names as hover detail", () => {
    const { container } = render(() => (
      <WbppLevelEditor
        session={contaminated()}
        chosenIndex={2}
        onSelect={() => {}}
        libraryRoot="/lib"
        separator="/"
      />
    ));
    const title = container.querySelectorAll("label")[0].getAttribute("title") ?? "";
    expect(title).toContain("M33");
    expect(title).toContain("NGC 7000");
    expect(title).toContain("2026-03-01");
  });

  it("pluralizes a single other target", () => {
    const s = session({
      levels: [level("/lib/M31", { is_contaminated: true, other_targets: ["M33"] })],
      default_level_index: 0,
    });
    const { container } = render(() => (
      <WbppLevelEditor session={s} chosenIndex={0} onSelect={() => {}} libraryRoot="/lib" separator="/" />
    ));
    expect(container.querySelectorAll("label")[0].textContent).toContain("+1 other target");
    expect(container.querySelectorAll("label")[0].textContent).not.toContain("targets");
  });

  it("calls onSelect with the clicked index", () => {
    const onSelect = vi.fn();
    const { getAllByRole } = render(() => (
      <WbppLevelEditor session={session()} chosenIndex={1} onSelect={onSelect} libraryRoot="/lib" separator="/" />
    ));
    fireEvent.click(getAllByRole("radio")[2]);
    expect(onSelect).toHaveBeenCalledTimes(1);
    expect(onSelect).toHaveBeenCalledWith(2);
  });

  it("escalates the cost to a warning chip when the contaminated level is selected", () => {
    const props = { session: contaminated(), onSelect: () => {}, libraryRoot: "/lib", separator: "/" };

    const unselected = render(() => <WbppLevelEditor {...props} chosenIndex={2} />);
    const plain = unselected.container.querySelectorAll("label")[0].querySelector(
      ".text-theme-warning",
    ) as HTMLElement;
    expect(plain.className).not.toContain("bg-theme-warning/15");

    const selected = render(() => <WbppLevelEditor {...props} chosenIndex={0} />);
    const chip = selected.container.querySelectorAll("label")[0].querySelector(
      ".text-theme-warning",
    ) as HTMLElement;
    expect(chip.className).toContain("bg-theme-warning/15");
    expect(chip.className).toContain("border-theme-warning/30");
  });

  it("emphasizes the selected segment in the resolved path", () => {
    const { container } = render(() => (
      <WbppLevelEditor session={session()} chosenIndex={1} onSelect={() => {}} libraryRoot="/lib" separator="/" />
    ));
    const path = container.querySelector(".overflow-x-auto") as HTMLElement;
    expect(path.textContent).toBe("/lib/M31/2026-03-04/LIGHT");
    const emphasized = Array.from(path.querySelectorAll("span")).filter((s) =>
      s.className.includes("font-semibold"),
    );
    expect(emphasized.length).toBe(1);
    expect(emphasized[0].textContent).toBe("2026-03-04");
  });

  it("renders the resolved path inside its own horizontal scroller", () => {
    const { container } = render(() => (
      <WbppLevelEditor session={session()} chosenIndex={0} onSelect={() => {}} libraryRoot="/lib" separator="/" />
    ));
    const scroller = container.querySelector(".overflow-x-auto") as HTMLElement;
    expect(scroller).toBeDefined();
    expect((scroller.querySelector("p") as HTMLElement).className).toContain("whitespace-nowrap");
  });

  it("renders the resolved path with the separator it was given", () => {
    const { container } = render(() => (
      <WbppLevelEditor
        session={session()}
        chosenIndex={0}
        onSelect={() => {}}
        libraryRoot={"D:\\Astro"}
        separator={"\\"}
      />
    ));
    const path = container.querySelector(".overflow-x-auto") as HTMLElement;
    expect(path.textContent).toBe("D:\\Astro\\M31\\2026-03-04\\LIGHT");
  });

  // The bug the separator prop exists to kill: with wbpp_default_os pinned to
  // windows and a posix-shaped root, the modal's plan writes "\" destinations.
  // Deriving the separator from the root here would render "/" against them.
  it("obeys the separator prop over the shape of the library root", () => {
    const { container } = render(() => (
      <WbppLevelEditor
        session={session()}
        chosenIndex={0}
        onSelect={() => {}}
        libraryRoot="/mnt/astro"
        separator={"\\"}
      />
    ));
    const path = container.querySelector(".overflow-x-auto") as HTMLElement;
    expect(path.textContent).toBe("/mnt/astro\\M31\\2026-03-04\\LIGHT");
  });

  it("groups the radios under one name derived from the session date", () => {
    const { getAllByRole } = render(() => (
      <WbppLevelEditor session={session()} chosenIndex={0} onSelect={() => {}} libraryRoot="/lib" separator="/" />
    ));
    const names = getAllByRole("radio").map((r) => (r as HTMLInputElement).name);
    expect(new Set(names).size).toBe(1);
    expect(names[0]).toBe("wbpp-level-2026-03-04");
  });

  it("checks only the chosen radio", () => {
    const { getAllByRole } = render(() => (
      <WbppLevelEditor session={session()} chosenIndex={2} onSelect={() => {}} libraryRoot="/lib" separator="/" />
    ));
    const checked = getAllByRole("radio").map((r) => (r as HTMLInputElement).checked);
    expect(checked).toEqual([false, false, true]);
  });

  // FIX 2: the list's order and indentation have to explain themselves. The
  // root anchors the top; indentation grows one step per level below it.
  it("anchors the list with the library root above the first level", () => {
    const { container, queryAllByRole } = render(() => (
      <WbppLevelEditor session={session()} chosenIndex={1} onSelect={() => {}} libraryRoot="/lib" separator="/" />
    ));
    const anchor = container.querySelector("p[title='/lib']") as HTMLElement;
    expect(anchor.textContent).toBe("/lib");
    // Anchor only: it is not a choice, so it must not join the radiogroup.
    expect(queryAllByRole("radio").length).toBe(3);
    expect(anchor.closest("[role='radiogroup']")).toBe(null);
  });

  it("indents each level one step deeper, starting inside the root", () => {
    const { container } = render(() => (
      <WbppLevelEditor session={session()} chosenIndex={0} onSelect={() => {}} libraryRoot="/lib" separator="/" />
    ));
    const pad = (el: HTMLElement) => el.style.getPropertyValue("padding-left");
    expect(pad(container.querySelector("p[title='/lib']") as HTMLElement)).toBe("8px");
    const rows = Array.from(container.querySelectorAll("label")) as HTMLElement[];
    expect(rows.map(pad)).toEqual(["22px", "36px", "50px"]);
  });

  it("states that each folder is contained by the one above it", () => {
    const { container } = render(() => (
      <WbppLevelEditor session={session()} chosenIndex={0} onSelect={() => {}} libraryRoot="/lib" separator="/" />
    ));
    // The user's model is containment, not the tree's depth vocabulary.
    expect(container.textContent).toContain("Each folder sits inside the one above it.");
    expect(container.textContent).not.toContain("shallowest");
    expect(container.textContent).not.toContain("deepest");
  });

  it("falls back to a message when the session has no levels", () => {
    const { container, queryAllByRole } = render(() => (
      <WbppLevelEditor
        session={session({ levels: [] })}
        chosenIndex={0}
        onSelect={() => {}}
        libraryRoot="/lib"
        separator="/"
      />
    ));
    expect(queryAllByRole("radio").length).toBe(0);
    expect(container.textContent).toContain("No frames found for this session.");
  });
});
