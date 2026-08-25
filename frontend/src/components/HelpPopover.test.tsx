import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, fireEvent } from "@solidjs/testing-library";
import HelpPopover from "./HelpPopover";

function setup() {
  const r = render(() => (
    <HelpPopover label="About Sessions" title="Sessions">
      <p>Guiding sessions catalogued for the rig.</p>
    </HelpPopover>
  ));
  const trigger = r.getByLabelText("About Sessions");
  return { ...r, trigger, wrapper: trigger.parentElement! };
}

describe("HelpPopover hover", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it("opens after the hover delay and closes after the leave grace, without taking focus", () => {
    const { trigger, wrapper } = setup();
    fireEvent.mouseEnter(wrapper);
    vi.advanceTimersByTime(100);
    expect(trigger.getAttribute("aria-expanded")).toBe("false");
    vi.advanceTimersByTime(100);
    expect(trigger.getAttribute("aria-expanded")).toBe("true");
    expect(document.querySelector('[role="dialog"]')).not.toBe(document.activeElement);

    fireEvent.mouseLeave(wrapper);
    vi.advanceTimersByTime(100);
    expect(trigger.getAttribute("aria-expanded")).toBe("true");
    vi.advanceTimersByTime(150);
    expect(trigger.getAttribute("aria-expanded")).toBe("false");
  });

  it("cancels the pending close when the pointer comes back", () => {
    const { trigger, wrapper } = setup();
    fireEvent.mouseEnter(wrapper);
    vi.advanceTimersByTime(200);
    fireEvent.mouseLeave(wrapper);
    fireEvent.mouseEnter(wrapper);
    vi.advanceTimersByTime(500);
    expect(trigger.getAttribute("aria-expanded")).toBe("true");
  });

  it("still opens on click and focuses the panel", () => {
    const { trigger } = setup();
    fireEvent.click(trigger);
    expect(trigger.getAttribute("aria-expanded")).toBe("true");
    expect(document.activeElement).toBe(document.querySelector('[role="dialog"]'));
  });
});
