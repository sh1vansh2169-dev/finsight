// The parts of the API's responses the app uses. Money is always a decimal
// string ("-120.00"): it is formatted for display, never used for arithmetic.

export type Money = string;
export type Basis = "source" | "user" | "rule" | "model" | "none";
export type TxnType =
  | "expense" | "income" | "transfer" | "refund" | "lent" | "borrowed"
  | "repayment_received" | "repayment_made" | "reversal" | "unknown";

export interface User {
  id: number;
  email: string;
  created_at: string;
}

export interface Transaction {
  id: number;
  date: string;
  description: string;
  amount: Money;
  direction: "debit" | "credit";
  currency: string;
  account: string;
  txn_type: TxnType;
  type_basis: Basis;
  category: string;
  category_basis: Basis;
  status: "posted" | "pending" | "failed" | "reversed" | "unknown";
  source: string;
  duplicate_of_id: number | null;
}

export interface TransactionPage {
  total: number;
  limit: number;
  offset: number;
  items: Transaction[];
}

export interface SeriesPoint {
  period: string;
  start: string;
  end: string;
  income: Money | null;
  expenses: Money | null;
  refunds: Money | null;
  spending: Money | null;
  net_cash_flow: Money | null;
  coverage: number;
}

export interface BudgetUse {
  category: string;
  currency: string;
  limit: Money;
  spent: Money;
  remaining: Money;
  percent_used: number;
  state: "on_track" | "close" | "over";
  message: string;
}

export interface Projection {
  start: string;
  end: string;
  net_change: { estimate: Money; cautious: Money | null; hopeful: Money | null };
  commitments: { money_in: Money; money_out: Money; money_out_high: Money };
  not_included: { if_others_repay_you: Money; if_you_repay_others: Money };
  reserve_for_commitments: Money;
  occurrences: { date: string; name: string; amount: Money }[];
  assumptions: string[];
}

export interface MajraSummary {
  currency: string;
  owed_to_you: Money;
  you_owe: Money;
  note: string;
  people: { person: { id: number; name: string }; owes_you: Money; you_owe: Money }[];
}

export interface Summary {
  income: Money;
  expenses: Money;
  refunds: Money;
  spending: Money;
  inflow: Money;
  outflow: Money;
  net_cash_flow: Money;
  warnings: string[];
  spending_by_category: Record<string, Money>;
}

export interface Dashboard {
  month: string;
  currency: string | null;
  sample_data: boolean;
  note: string;
  summary: Summary | null;
  daily: SeriesPoint[];
  monthly: SeriesPoint[];
  recent_transactions: Transaction[];
  budgets: BudgetUse[];
  warnings: string[];
  open_duplicate_reviews: number;
  money_majra: MajraSummary | null;
  outlook: (Projection & { note: string }) | null;
}

export interface ImportRow {
  source_row: number;
  outcome: "new" | "suspected" | "duplicate" | "rejected";
  reason: string | null;
  transaction: { date: string; description: string; amount: Money; category: string; txn_type: TxnType } | null;
  raw: Record<string, string> | null;
}

export interface ImportBatch {
  id: number;
  filename: string;
  status: "previewed" | "committed" | "discarded";
  total_rows: number;
  rejected_rows: number;
  new_rows: number;
  suspected_rows: number;
  duplicate_rows: number;
  inserted_rows: number;
  warnings: string[];
}

export interface ImportDetail {
  batch: ImportBatch;
  rows: ImportRow[];
}

export interface Account {
  id: number;
  name: string;
  currency: string;
}

export interface Recommendation {
  kind: string;
  priority: number;
  title: string;
  message: string;
  action: string | null;
}

export interface Health {
  status: string;
  version: string;
  sample_data: boolean;
}

export interface MajraPerson {
  id: number;
  name: string;
  is_me: boolean;
}

export interface MajraGroup {
  id: number;
  name: string;
  kind: "group" | "direct";
  currency: string;
  members: MajraPerson[];
}

export interface MajraGroupDetail {
  group: MajraGroup;
  balances: { person: MajraPerson; balance: Money; status: "is_owed" | "owes" | "settled" }[];
  balances_sum_to_zero: boolean;
  settlement: { payer: MajraPerson; receiver: MajraPerson; amount: Money }[];
  settlement_is_minimal: boolean;
  entries: MajraEntry[];
}

export interface UnusualPayment {
  transaction: Transaction;
  reason: string;
  score: number;
}

export interface UnusualList {
  method: string;
  note: string;
  payments: UnusualPayment[];
}

export interface MajraEntry {
  id: number;
  kind: "expense" | "loan" | "payment";
  description: string;
  date: string;
  amount: Money;
  paid_by_id: number;
  paid_to_id: number | null;
  split_method: string | null;
  shares: { person_id: number; amount: Money }[];
  transaction_id: number | null;
  voided: boolean;
  void_reason: string | null;
}

export type SplitMethod = "equal" | "exact" | "percent" | "shares";
