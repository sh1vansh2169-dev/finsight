import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import type { DuplicateCandidate, SimProjection, Simulation } from "../api/types";
import { txn } from "./fixtures";
import { type Call, fakeApi, HEALTH, ME, renderAt } from "./helpers";

const signedIn = { "GET /auth/me": ME, "GET /health": HEALTH };
const posts = (calls: Call[], path: string) => calls.filter((c) => c.method !== "GET" && c.path === path);

const BANK = txn({ id: 11, description: "CHAI POINT", source: "bank.csv" });
const APP = txn({ id: 12, description: "Chai Point UPI", source: "payapp.csv" });
const pair = (over: Partial<DuplicateCandidate> = {}): DuplicateCandidate => ({
  id: 4, score: 86, confidence: "high", reasons: ["Same amount", "Dates one day apart"], status: "open",
  kept_transaction_id: null, transactions: [BANK, APP], ...over,
});

describe("duplicate review", () => {
  it("keeps the record the user picks, or keeps both", async () => {
    const calls = fakeApi({
      ...signedIn,
      "GET /review/duplicates": (c) => ({ body: c.path.includes("status=all") ? [pair()] : [pair()] }),
      "POST /review/duplicates/4/resolve": (c) => ({ body: pair({ status: (c.body as { decision: string }).decision as "duplicate" }) }),
    });
    renderAt("/transactions/review");
    const user = userEvent.setup();
    expect(await screen.findByText("Very likely the same")).toBeInTheDocument();
    expect(screen.getByText(/not a probability/)).toBeInTheDocument();
    expect(screen.getByText("Dates one day apart")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Same payment: keep the second" }));
    await user.click(screen.getByRole("button", { name: "Different payments" }));
    await waitFor(() => expect(posts(calls, "/review/duplicates/4/resolve").map((c) => c.body)).toEqual([
      { decision: "duplicate", keep_transaction_id: 12 },
      { decision: "distinct" },
    ]));
  });

  it("undoes a decision", async () => {
    const calls = fakeApi({
      ...signedIn,
      "GET /review/duplicates": (c) => ({ body: c.path.includes("status=all") ? [pair({ status: "duplicate", kept_transaction_id: 11 })] : [] }),
      "POST /review/duplicates/4/reopen": pair(),
    });
    renderAt("/transactions/review");
    expect(await screen.findByText("Nothing to review")).toBeInTheDocument();
    expect(await screen.findByText("Same payment: one record kept")).toBeInTheDocument();
    await userEvent.setup().click(screen.getByRole("button", { name: "Undo" }));
    await waitFor(() => expect(posts(calls, "/review/duplicates/4/reopen")).toHaveLength(1));
  });

  it("marks possible duplicates in the transaction list and links to the review", async () => {
    fakeApi({
      ...signedIn, "GET /categories": [], "GET /accounts": [],
      "GET /transactions": { total: 3, limit: 50, offset: 0, items: [BANK, APP, txn({ id: 13, description: "RENT" })] },
      "GET /review/duplicates": [pair()],
      "GET /ml/category-suggestions": { model_version: "v1", threshold: 0.7, note: "", suggestions: [] },
    });
    renderAt("/transactions");
    const link = await screen.findByRole("link", { name: "1 possible duplicate(s) to review" });
    expect(link).toHaveAttribute("href", "/transactions/review");
    expect(screen.getAllByText("Possible duplicate")).toHaveLength(2);
    const rent = screen.getByText("RENT").closest("li")!;
    expect(within(rent).queryByText("Possible duplicate")).toBeNull();
  });
});

describe("category suggestions and unusual payments", () => {
  const suggestion = {
    transaction: txn({ id: 21, description: "APOLLO PHARMACY", category: "Uncategorized", category_basis: "none" }),
    category: "Health", confidence: 0.82, confident: true, alternatives: [{ category: "Shopping", confidence: 0.1 }],
  };

  it("asks rather than tells, and saves the user's choice", async () => {
    const calls = fakeApi({
      ...signedIn,
      "GET /ml/category-suggestions": { model_version: "v1", threshold: 0.7, note: "Suggestions only. Trained on synthetic data so far; accept one with PATCH /api/v1/transactions/{id}.", suggestions: [suggestion] },
      "PATCH /transactions/21": txn({ id: 21, category: "Shopping" }),
    });
    renderAt("/transactions/suggestions");
    expect(await screen.findByText("Health")).toBeInTheDocument();
    expect(screen.getByText("(82% sure)")).toBeInTheDocument();
    expect(screen.getByText("Suggestions only. Trained on synthetic data so far.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Apply those/ })).toBeNull(); // nothing at 90% or more
    await userEvent.setup().click(screen.getByRole("button", { name: "Shopping (10%)" }));
    await waitFor(() => expect(calls.find((c) => c.method === "PATCH")?.body).toEqual({ category: "Shopping" }));
  });

  it("explains when there is no model", async () => {
    fakeApi({ ...signedIn, "GET /ml/category-suggestions": () => ({ status: 404, body: { detail: "No categorisation model" } }) });
    renderAt("/transactions/suggestions");
    expect(await screen.findByText("No suggestion model yet")).toBeInTheDocument();
  });

  it("lets the user say an unusual payment was expected", async () => {
    const calls = fakeApi({
      ...signedIn, "GET /recommendations": [], "GET /dashboard": { summary: null, currency: null },
      "GET /ml/unusual": { method: "robust z", note: "Not a fraud check.", payments: [{ transaction: txn({ id: 31, description: "LAPTOP STORE", amount: "-90000.00" }), reason: "About 9 times your usual Shopping payment.", score: 9.1 }] },
      "POST /ml/unusual/31/dismiss": () => ({ status: 204 }),
    });
    renderAt("/insights");
    await userEvent.setup().click(await screen.findByRole("button", { name: "LAPTOP STORE: this was expected" }));
    await waitFor(() => expect(posts(calls, "/ml/unusual/31/dismiss").map((c) => c.body)).toEqual([{}]));
    expect(screen.queryByText(/fraud/i)?.textContent).toBe("Not a fraud check."); // the only mention, and a denial
  });
});

describe("budgets", () => {
  it("shows use against the limit and saves an exact limit", async () => {
    const calls = fakeApi({
      ...signedIn, "GET /categories": ["Dining", "Groceries", "Uncategorized"],
      "GET /budgets": [{ id: 1, category: "Dining", currency: "INR", monthly_limit: "3000.00" }],
      "GET /budgets/usage": [{ category: "Dining", currency: "INR", limit: "3000.00", spent: "3250.00", remaining: "-250.00", percent_used: 108, state: "over", message: "₹250.00 over this month." }],
      "PUT /budgets": { id: 2, category: "Groceries", currency: "INR", monthly_limit: "8000.50" },
    });
    renderAt("/insights/budgets");
    expect(await screen.findByText("₹3,250.00 of ₹3,000.00")).toBeInTheDocument();
    expect(screen.getByText("Over the limit.")).toBeInTheDocument();
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Add budget" }));
    const category = screen.getByLabelText("Category");
    expect(within(category).queryByRole("option", { name: "Dining" })).toBeNull(); // already has one
    expect(within(category).queryByRole("option", { name: "Uncategorized" })).toBeNull();
    await user.selectOptions(category, "Groceries");
    await user.type(screen.getByLabelText("Monthly limit"), "8,000.5");
    await user.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(posts(calls, "/budgets")[0]?.body).toEqual({ category: "Groceries", monthly_limit: "8000.50" }));
  });
});

describe("bills and income", () => {
  it("confirms a detected regular payment, pauses a commitment and shows what to keep aside", async () => {
    const calls = fakeApi({
      ...signedIn,
      "GET /commitments/upcoming": { currency: "INR", start: "2026-03-27", end: "2026-04-26", reserve: "23212.02",
        occurrences: [{ date: "2026-04-03", name: "Rent", amount: "-22000.00", up_to: null }, { date: "2026-04-10", name: "Electricity", amount: "-1100.00", up_to: "1212.02" }] },
      "GET /commitments": [{ id: 7, name: "Rent", direction: "debit", amount: "22000.00", amount_varies: false, high: null, currency: "INR",
        cadence: "monthly", next_due: "2026-04-03", end_date: null, category: "Housing", source: "detected", status: "active" }],
      "GET /recurring": [{ key: "streamflix", name: "STREAMFLIX", direction: "debit", cadence: "monthly", typical_amount: "649.00", low: "649.00",
        high: "649.00", amount_varies: false, occurrences: 4, last: "2026-03-05", next_expected: "2026-04-05", category: "Entertainment",
        confidence: 90, reasons: ["Same amount each month."], may_have_stopped: false, is_commitment: false }],
      "POST /commitments/confirm": { id: 8 },
      "PATCH /commitments/7": { id: 7 },
    });
    renderAt("/insights/bills");
    expect(await screen.findByText("₹23,212.02")).toBeInTheDocument();
    expect(screen.getByText("up to ₹1,212.02")).toBeInTheDocument();
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Confirm STREAMFLIX as a commitment" }));
    await user.click(screen.getByRole("button", { name: "Pause" }));
    await waitFor(() => {
      expect(posts(calls, "/commitments/confirm")[0]?.body).toEqual({ key: "streamflix" });
      expect(posts(calls, "/commitments/7")[0]?.body).toEqual({ status: "paused" });
    });
  });
});

describe("what-if", () => {
  const projection = (over: Partial<SimProjection> = {}): SimProjection => ({
    start: "2026-03-27", end: "2026-04-26", currency: "INR",
    net_change: { estimate: "47640.23", cautious: "43634.26", hopeful: "52475.35" }, balance: null,
    commitments: { money_in: "85000.00", money_out: "23861.00", money_out_high: "23973.02" },
    everyday_spending: { estimate: "13498.77", low: "8000.00", high: "17000.00", per_day: "449.96", history_days: 86 },
    not_included: { if_others_repay_you: "2000.00", if_you_repay_others: "0.00" }, reserve_for_commitments: "25358.02",
    occurrences: [], path: [], assumptions: ["Everyday spending is your average from the last 86 days."], changes: [], ...over,
  });

  it("shows a range, never counts money owed to you, and compares a change", async () => {
    const calls = fakeApi({
      ...signedIn, "GET /categories": [], "GET /commitments": [], "GET /majra/people": [],
      "POST /simulate": (c) => {
        const body = c.body as { scenarios: unknown[]; starting_balance?: string };
        const result: Simulation = { note: "An estimate, not a promise.", baseline: projection() };
        if (body.scenarios.length > 0) {
          result.scenario = projection({ net_change: { estimate: "17640.23", cautious: "13634.26", hopeful: "22475.35" }, changes: ["Added a purchase of ₹30,000.00."] });
          result.difference = { net_change: "-30000.00", balance: null };
        }
        return { body: result };
      },
    });
    renderAt("/insights/what-if");
    expect(await screen.findByText("Likely between +₹43,634.26 and +₹52,475.35")).toBeInTheDocument();
    expect(screen.getByText(/Not counted: ₹2,000.00 that others owe you/)).toBeInTheDocument();

    const user = userEvent.setup();
    await user.type(screen.getByLabelText("What (optional)"), "a laptop");
    await user.type(screen.getByLabelText("Amount"), "30000");
    await user.click(screen.getByRole("button", { name: "Add this change" }));
    expect(await screen.findByText("With your changes")).toBeInTheDocument();
    expect(screen.getByText("−₹30,000.00")).toBeInTheDocument();
    const last = posts(calls, "/simulate").at(-1)!.body;
    expect(last).toEqual({ horizon_days: 30, scenarios: [{ kind: "purchase", amount: "30000.00", date: "2026-03-28", description: "a laptop" }] });
    expect(calls.every((c) => c.method !== "POST" || c.headers["X-MoneyOS-CSRF"] === "1")).toBe(true);

    await user.type(screen.getByLabelText(/Money you have now/), "45,000");
    await waitFor(() => expect(posts(calls, "/simulate").at(-1)!.body).toMatchObject({ starting_balance: "45000.00" }));
  });
});
