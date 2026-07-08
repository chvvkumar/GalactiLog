import { describe, it, expect } from "vitest";
import { render } from "@solidjs/testing-library";
import StatsCard from "./StatsCard";
import type { SummaryStats } from "../../api/types";

const sampleStats: SummaryStats = {
  count: 100,
  min: 1.23,
  max: 9.87,
  mean: 5.0,
  median: 4.95,
  std_dev: 1.5,
};

describe("StatsCard", () => {
  it("renders all six stat values", () => {
    const { getByText } = render(() => <StatsCard stats={sampleStats} />);

    expect(getByText("100")).toBeDefined();
    expect(getByText("1.23")).toBeDefined();
    expect(getByText("9.87")).toBeDefined();
    expect(getByText("5.00")).toBeDefined();
    expect(getByText("4.95")).toBeDefined();
    expect(getByText("1.50")).toBeDefined();
  });

  it("renders the optional label when provided", () => {
    const { getByText } = render(() => (
      <StatsCard stats={sampleStats} label="HFR Distribution" />
    ));
    expect(getByText("HFR Distribution")).toBeDefined();
  });

  it("does not render a label element when label is omitted", () => {
    const { queryByText } = render(() => <StatsCard stats={sampleStats} />);
    expect(queryByText("HFR Distribution")).toBeNull();
  });

  it("abbreviates large numbers to one decimal place", () => {
    const bigStats: SummaryStats = { ...sampleStats, max: 12345.6, mean: 10.5 };
    const { getByText } = render(() => <StatsCard stats={bigStats} />);
    // max >= 1000: formatted as toFixed(0) = "12346"
    expect(getByText("12346")).toBeDefined();
    // mean >= 10: formatted as toFixed(1) = "10.5"
    expect(getByText("10.5")).toBeDefined();
  });
});
