import { describe, it, expect } from "vitest";
import { render } from "@solidjs/testing-library";
import { Router, Route } from "@solidjs/router";
import ActivityActionLink, { eventAction } from "./ActionLink";
import type { ActivityEvent } from "../../api/types";

function event(details: Record<string, unknown> | null): ActivityEvent {
  return {
    id: 1,
    timestamp: "2026-08-24T00:00:00Z",
    category: "scan",
    severity: "warning",
    event_type: "phd2_correlation_unattributed",
    message: "2 guide logs could not be attributed",
    details,
  } as ActivityEvent;
}

function renderLink(ev: ActivityEvent) {
  return render(() => (
    <Router>
      <Route path="/" component={() => <ActivityActionLink event={ev} />} />
    </Router>
  ));
}

describe("ActivityActionLink", () => {
  it("renders the action as a link when details.action is present", async () => {
    const ev = event({
      unattributed: 2,
      action: { label: "Map PHD2 profiles", href: "/settings?tab=equipment#phd2-profiles" },
    });
    const { findByText } = renderLink(ev);
    const link = await findByText("Map PHD2 profiles");
    expect(link.getAttribute("href")).toBe("/settings?tab=equipment#phd2-profiles");
  });

  it("renders nothing when the event has no action", async () => {
    const { container } = renderLink(event({ unattributed: 2 }));
    await Promise.resolve();
    expect(container.querySelector("a")).toBeNull();
  });
});

describe("eventAction", () => {
  it("returns null for null details and for malformed actions", () => {
    expect(eventAction(event(null))).toBeNull();
    expect(eventAction(event({ action: { label: "no href" } }))).toBeNull();
    expect(eventAction(event({ action: "nope" }))).toBeNull();
    expect(eventAction(event({ action: { label: "", href: "/settings" } }))).toBeNull();
  });

  it("rejects any href that is not a single-slash in-app path", () => {
    for (const href of [
      "https://evil.com",
      "//evil.com",
      "javascript://%0aalert(1)",
      "data:text/html,<script>alert(1)</script>",
      "settings?tab=scan",
    ]) {
      expect(eventAction(event({ action: { label: "Go", href } }))).toBeNull();
    }
  });
});

describe("ActivityActionLink href hardening", () => {
  it("renders no anchor for off-site or scripted hrefs", async () => {
    for (const href of ["https://evil.com", "//evil.com", "javascript://%0aalert(1)"]) {
      const { container } = renderLink(event({ action: { label: "Go", href } }));
      await Promise.resolve();
      expect(container.querySelector("a")).toBeNull();
    }
  });
});
