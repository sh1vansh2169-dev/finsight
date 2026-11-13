import { describe, expect, it } from "vitest";

import { categoryLabel, isNegative, money, signedMoney } from "../lib/format";

describe("money formatting", () => {
  it("formats exact decimal strings in Indian style", () => {
    expect(money("85000.00")).toBe("₹85,000.00");
    expect(money("123456.78")).toBe("₹1,23,456.78");
    expect(money("-22000.00")).toBe("₹22,000.00"); // the sign is shown separately
  });

  it("never rounds through floating point", () => {
    // 12345678901234.57 is not representable as a float; as a string it stays exact.
    expect(money("12345678901234.57")).toBe("₹1,23,45,67,89,01,234.57");
  });

  it("shows unknown as unknown, never as zero", () => {
    expect(money(null)).toBe("Unknown");
  });

  it("signs amounts with a true minus", () => {
    expect(signedMoney("-120.00")).toBe("−₹120.00");
    expect(signedMoney("120.00")).toBe("+₹120.00");
    expect(signedMoney("-0.00")).toBe("₹0.00");
    expect(isNegative("-0.00")).toBe(false);
  });

  it("names transfers by their type instead of 'Uncategorized'", () => {
    expect(categoryLabel({ category: "Uncategorized", txn_type: "transfer" })).toBe("Between your accounts");
    expect(categoryLabel({ category: "Uncategorized", txn_type: "unknown" })).toBe("Uncategorized");
    expect(categoryLabel({ category: "Dining", txn_type: "expense" })).toBe("Dining");
  });
});
