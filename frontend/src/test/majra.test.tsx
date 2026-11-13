import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import type { MajraGroupDetail } from "../api/types";
import { fromMinor, toMinor } from "../lib/format";
import { splitCheck } from "../pages/MajraForms";
import { fakeApi, HEALTH, ME, renderAt } from "./helpers";

describe("exact money helpers", () => {
  it("parses typed amounts into whole paise", () => {
    expect(toMinor("1250")).toBe(125000n);
    expect(toMinor("1,250.5")).toBe(125050n);
    expect(toMinor("0.1")).toBe(10n);
    expect(toMinor("12.345")).toBeNull();
    expect(toMinor("-5")).toBeNull();
    expect(toMinor("1e3")).toBeNull();
    expect(toMinor("")).toBeNull();
    expect(fromMinor(125050n)).toBe("1250.50");
    expect(fromMinor(7n)).toBe("0.07");
  });

  it("checks splits exactly, without floating point", () => {
    // 0.1 + 0.2 is not 0.3 in floating point; in paise it is.
    expect(splitCheck("exact", "0.30", ["0.1", "0.2"]).ok).toBe(true);
    expect(splitCheck("exact", "100", ["60", "30"])).toEqual({ ok: false, message: "₹90.00 of ₹100.00: ₹10.00 left to assign." });
    expect(splitCheck("exact", "100", ["60", "50"]).message).toContain("₹10.00 too much");
    expect(splitCheck("percent", "999", ["33.33", "33.33", "33.34"]).ok).toBe(true);
    expect(splitCheck("percent", "999", ["50", "40"]).ok).toBe(false);
    expect(splitCheck("shares", "999", ["2", "1"]).ok).toBe(true);
    expect(splitCheck("shares", "999", ["0", "0"]).ok).toBe(false);
    expect(splitCheck("equal", "999", []).ok).toBe(false);
  });
});

const ME_P = { id: 1, name: "Me", is_me: true };
const ASHA = { id: 2, name: "Asha", is_me: false };
const RAVI = { id: 3, name: "Ravi", is_me: false };
const GROUP = { id: 10, name: "Goa trip", kind: "group" as const, currency: "INR", members: [ME_P, ASHA, RAVI] };

function detail(over: Partial<MajraGroupDetail> = {}): MajraGroupDetail {
  return {
    group: GROUP,
    balances: [
      { person: ME_P, balance: "600.00", status: "is_owed" },
      { person: ASHA, balance: "-300.00", status: "owes" },
      { person: RAVI, balance: "-300.00", status: "owes" },
    ],
    balances_sum_to_zero: true,
    settlement: [
      { payer: ASHA, receiver: ME_P, amount: "300.00" },
      { payer: RAVI, receiver: ME_P, amount: "300.00" },
    ],
    settlement_is_minimal: true,
    entries: [{
      id: 5, kind: "expense", description: "Dinner", date: "2026-11-01", amount: "900.00", paid_by_id: 1, paid_to_id: null,
      split_method: "equal", shares: [], transaction_id: null, voided: false, void_reason: null,
    }],
    ...over,
  };
}

const base = {
  "GET /auth/me": ME, "GET /health": HEALTH,
  "GET /majra/summary": [{ currency: "INR", owed_to_you: "600.00", you_owe: "0.00", note: "Expected back from others: not guaranteed.", people: [] }],
  "GET /majra/groups": [GROUP],
  "GET /majra/people": [ME_P, ASHA, RAVI],
  "GET /majra/groups/10": detail(),
};

describe("money majra forms", () => {
  it("adds an expense split by exact amounts, sending exact strings", async () => {
    const calls = fakeApi({ ...base, "POST /majra/groups/10/expenses": () => ({ status: 201, body: detail() }) });
    renderAt("/money-majra");
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Add expense" }));
    await user.type(screen.getByLabelText("What was it"), "Scooter rental");
    await user.type(screen.getByLabelText("Total (INR)"), "1,000.10");
    await user.selectOptions(screen.getByLabelText("Split"), "exact");
    await user.click(screen.getByRole("checkbox", { name: "Ravi" })); // Ravi didn't ride
    await user.type(screen.getByLabelText("You: amount"), "500.05");
    await user.type(screen.getByLabelText("Asha: amount"), "500");
    expect(screen.getByText("₹1,000.05 of ₹1,000.10: ₹0.05 left to assign.")).toBeInTheDocument();
    const save = screen.getByRole("button", { name: "Add expense" });
    expect(save).toBeDisabled();
    await user.type(screen.getByLabelText("Asha: amount"), ".05");
    expect(screen.getByText("Adds up to ₹1,000.10.")).toBeInTheDocument();
    await user.click(save);
    await waitFor(() => expect(calls.find((c) => c.method === "POST")?.body).toMatchObject({
      description: "Scooter rental", amount: "1000.10", paid_by_id: 1,
      split: { method: "exact", participants: [{ person_id: 1, value: "500.05" }, { person_id: 2, value: "500.05" }] },
    }));
    expect(calls.find((c) => c.method === "POST")!.headers["X-MoneyOS-CSRF"]).toBe("1");
  });

  it("records a suggested repayment and asks before recording a repeat", async () => {
    let attempts = 0;
    const calls = fakeApi({
      ...base,
      "POST /majra/groups/10/payments": (call) => {
        attempts += 1;
        const body = call.body as { confirm_duplicate: boolean };
        return body.confirm_duplicate
          ? { status: 201, body: detail() }
          : { status: 409, body: { detail: "an identical payment on the same day is already recorded (entry 6)" } };
      },
    });
    renderAt("/money-majra");
    const user = userEvent.setup();
    await user.click((await screen.findAllByRole("button", { name: "Record as paid" }))[0]!);
    expect(screen.getByLabelText("Who paid")).toHaveValue("2");
    expect(screen.getByLabelText("Amount")).toHaveValue("300.00");
    expect(screen.getByText(/MoneyOS never sends money/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Record payment" }));

    expect(await screen.findByText(/Is this a second, separate payment\?/)).toBeInTheDocument();
    expect(attempts).toBe(1); // nothing retried behind the user's back
    await user.click(screen.getByRole("button", { name: "Yes, it's a second payment" }));
    await waitFor(() => expect(attempts).toBe(2));
    expect(calls.filter((c) => c.method === "POST").map((c) => (c.body as { confirm_duplicate: boolean }).confirm_duplicate))
      .toEqual([false, true]);
    expect(calls.at(-1)?.method).toBe("GET"); // the group refreshes afterwards
  });

  it("records money lent to one person", async () => {
    const calls = fakeApi({ ...base, "POST /majra/loans": () => ({ status: 201, body: detail() }) });
    renderAt("/money-majra");
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Lend or borrow" }));
    await user.selectOptions(await screen.findByLabelText("To"), "Ravi");
    await user.type(screen.getByLabelText("Amount"), "2500");
    await user.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(calls.find((c) => c.path === "/majra/loans")?.body).toMatchObject({
      person_id: 3, direction: "lent", amount: "2500.00", description: "Lent",
    }));
  });

  it("cancels an entry only with a reason, keeping it in the history", async () => {
    const calls = fakeApi({
      ...base,
      "POST /majra/entries/5/void": () => ({ body: detail({ entries: [{ ...detail().entries[0]!, voided: true, void_reason: "Entered twice" }] }) }),
    });
    renderAt("/money-majra");
    const user = userEvent.setup();
    await user.click(await screen.findByText("History (1)"));
    await user.click(screen.getByRole("button", { name: "Cancel entry" }));
    const confirm = screen.getAllByRole("button", { name: "Cancel entry" }).at(-1)!;
    expect(confirm).toBeDisabled();
    await user.type(screen.getByLabelText(/Why cancel "Dinner"\?/), "Entered twice");
    await user.click(confirm);
    expect(await screen.findByText("Cancelled: Entered twice")).toBeInTheDocument();
    expect(calls.find((c) => c.path === "/majra/entries/5/void")?.body).toEqual({ reason: "Entered twice" });
  });
});

