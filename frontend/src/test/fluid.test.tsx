import { act, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { CountUp } from "../components/ui";
import { dashboard } from "./fixtures";
import { fakeApi, HEALTH, ME, renderAt } from "./helpers";

describe("count-up figures", () => {
  it("gives screen readers the exact figure at once and ends on the exact figure", async () => {
    const { container } = render(<CountUp value="175164.59" signed />);
    expect(screen.getByText("+₹1,75,164.59", { selector: ".sr-only" })).toBeInTheDocument();
    const shown = container.querySelector('[aria-hidden="true"]')!;
    await waitFor(() => expect(shown.textContent).toBe("+₹1,75,164.59"), { timeout: 3000 });
  });

  it("a late animation frame never replaces the exact figure (busy device)", () => {
    vi.useFakeTimers();
    const frames: FrameRequestCallback[] = [];
    vi.stubGlobal("requestAnimationFrame", (cb: FrameRequestCallback) => frames.push(cb));
    vi.stubGlobal("cancelAnimationFrame", () => {});
    try {
      const { container } = render(<CountUp value="175164.59" signed duration={1000} />);
      const shown = () => container.querySelector('[aria-hidden="true"]')!.textContent;
      act(() => vi.advanceTimersByTime(1100)); // the safety timer shows the exact figure
      expect(shown()).toBe("+₹1,75,164.59");
      act(() => frames.forEach((cb) => cb(300))); // then a frame queued long ago finally runs
      expect(shown()).toBe("+₹1,75,164.59");
    } finally {
      vi.useRealTimers();
    }
  });

  it("does not animate when the device asks for less motion", () => {
    vi.stubGlobal("matchMedia", (query: string) => ({
      matches: query.includes("reduce"), media: query, addEventListener() {}, removeEventListener() {},
    }));
    const { container } = render(<CountUp value="-22000.00" signed />);
    expect(container.querySelector('[aria-hidden="true"]')!.textContent).toBe("−₹22,000.00"); // first frame is final
  });
});

describe("tab bar", () => {
  it("moves the pill to the open section, sub-pages included", async () => {
    fakeApi({ "GET /auth/me": ME, "GET /health": HEALTH, "GET /dashboard": dashboard(),
      "GET /budgets": [], "GET /budgets/usage": [], "GET /categories": [] });
    const { container } = renderAt("/insights/budgets");
    await screen.findByText("No budgets yet");
    const pill = container.querySelector(".nav-pill") as HTMLElement;
    expect(pill.style.transform).toBe("translateX(300%)"); // Insights is the 4th of 5
  });
});
