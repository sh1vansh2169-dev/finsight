import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { percent } from "../pages/Suggestions";
import { addDays } from "../pages/WhatIf";
import { txn } from "./fixtures";
import { fakeApi, HEALTH, ME, renderAt } from "./helpers";

describe("model scores are never shown as certainty", () => {
  it("caps the displayed confidence", () => {
    expect(percent(0.9999)).toBe("over 99%");
    expect(percent(0.995)).toBe("over 99%");
    expect(percent(0.994)).toBe("99%");
    expect(percent(0.82)).toBe("82%");
    expect(percent(0.004)).toBe("under 1%");
  });

  it("hides alternatives the model gives almost no weight", async () => {
    fakeApi({
      "GET /auth/me": ME, "GET /health": HEALTH,
      "GET /ml/category-suggestions": {
        model_version: "v1", threshold: 0.7, note: "Suggestions only.",
        suggestions: [{
          transaction: txn({ id: 5, description: "CHAI POINT", category: "Uncategorized" }), category: "Dining",
          confidence: 0.9991, confident: true,
          alternatives: [{ category: "Groceries", confidence: 0.06 }, { category: "Housing", confidence: 0.0004 }],
        }],
      },
    });
    renderAt("/transactions/suggestions");
    expect(await screen.findByText("(over 99% sure)")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Groceries (6%)" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Housing/ })).toBeNull();
  });
});

describe("what-if dates", () => {
  it("adds calendar days across month and year ends", () => {
    expect(addDays("2026-03-27", 1)).toBe("2026-03-28");
    expect(addDays("2026-03-31", 1)).toBe("2026-04-01");
    expect(addDays("2026-12-31", 1)).toBe("2027-01-01");
    expect(addDays("2028-02-28", 1)).toBe("2028-02-29");
  });
});
