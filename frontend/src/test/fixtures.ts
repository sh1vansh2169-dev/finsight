// Synthetic API responses for the page tests. No real data.
import type { Dashboard, ImportDetail, Transaction } from "../api/types";

export function txn(over: Partial<Transaction> = {}): Transaction {
  return {
    id: 1, date: "2026-10-05", description: "CHAI POINT KORAMANGALA", amount: "-120.00", direction: "debit",
    currency: "INR", account: "Demo Savings", txn_type: "expense", type_basis: "rule", category: "Dining",
    category_basis: "rule", status: "posted", source: "demo.csv", duplicate_of_id: null, ...over,
  };
}

export function dashboard(over: Partial<Dashboard> = {}): Dashboard {
  return {
    month: "2026-10", currency: "INR", sample_data: false, note: "From 3 statements.",
    summary: {
      income: "85000.00", expenses: "22500.00", refunds: "500.00", spending: "22000.00", inflow: "85500.00",
      outflow: "22500.00", net_cash_flow: "63000.00", warnings: [], spending_by_category: { Dining: "120.00" },
    },
    daily: [
      { period: "2026-10-01", start: "2026-10-01", end: "2026-10-01", income: "0.00", expenses: "120.00", refunds: "0.00", spending: "120.00", net_cash_flow: "-120.00", coverage: 1 },
      { period: "2026-10-02", start: "2026-10-02", end: "2026-10-02", income: null, expenses: null, refunds: null, spending: null, net_cash_flow: null, coverage: 0 },
    ],
    monthly: [], budgets: [], warnings: [], open_duplicate_reviews: 0, money_majra: null, outlook: null,
    recent_transactions: [txn(), txn({ id: 2, description: "TRANSFER TO DEMO CARD", category: "Uncategorized", txn_type: "transfer", category_basis: "none" })],
    ...over,
  };
}

export const PREVIEW: ImportDetail = {
  batch: {
    id: 7, filename: "october.csv", status: "previewed", total_rows: 3, rejected_rows: 1, new_rows: 1,
    suspected_rows: 0, duplicate_rows: 1, inserted_rows: 0, warnings: [],
  },
  rows: [
    { source_row: 2, outcome: "new", reason: null, raw: null,
      transaction: { date: "2026-10-05", description: "CHAI POINT", amount: "-120.00", category: "Dining", txn_type: "expense" } },
    { source_row: 3, outcome: "duplicate", reason: "Already recorded as transaction 1", raw: null,
      transaction: { date: "2026-10-04", description: "RENT", amount: "-20000.00", category: "Housing", txn_type: "expense" } },
    { source_row: 4, outcome: "rejected", reason: "amount is not a number", raw: { date: "2026-10-06", amount: "abc" }, transaction: null },
  ],
};
