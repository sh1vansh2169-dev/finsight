// Display formatting. Amounts arrive as exact decimal strings and are passed to
// Intl as strings, so no floating-point rounding happens on the way to the screen.

const formatters = new Map<string, Intl.NumberFormat>();

function formatter(currency: string): Intl.NumberFormat {
  let f = formatters.get(currency);
  if (!f) {
    f = new Intl.NumberFormat("en-IN", { style: "currency", currency, minimumFractionDigits: 2 });
    formatters.set(currency, f);
  }
  return f;
}

/** "-22000.00" -> "₹22,000.00" (no sign); null -> "Unknown". */
export function money(value: string | null | undefined, currency = "INR"): string {
  if (value === null || value === undefined) return "Unknown";
  const unsigned = value.startsWith("-") ? value.slice(1) : value;
  return formatter(currency).format(unsigned as Intl.StringNumericLiteral);
}

/** "-22000.00" -> "−₹22,000.00"; "85000.00" -> "+₹85,000.00" (true minus sign). */
export function signedMoney(value: string, currency = "INR"): string {
  if (/^-?0+(\.0+)?$/.test(value)) return money("0", currency);
  return `${value.startsWith("-") ? "−" : "+"}${money(value, currency)}`;
}

export function isNegative(value: string): boolean {
  return value.startsWith("-") && !/^-0+(\.0+)?$/.test(value);
}

export function shortDate(iso: string): string {
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(Date.UTC(y!, m! - 1, d!)).toLocaleDateString("en-IN", { day: "numeric", month: "short", timeZone: "UTC" });
}

export function monthLabel(period: string): string {
  const [y, m] = period.split("-").map(Number);
  return new Date(Date.UTC(y!, m! - 1, 1)).toLocaleDateString("en-IN", { month: "long", year: "numeric", timeZone: "UTC" });
}

const BASIS_LABEL: Record<string, string> = {
  source: "From your file",
  user: "Set by you",
  rule: "Inferred",
  model: "Suggested",
  none: "Not known",
};

export function basisLabel(basis: string): string {
  return BASIS_LABEL[basis] ?? basis;
}

const TYPE_LABEL: Record<string, string> = {
  expense: "Spending",
  income: "Income",
  transfer: "Between your accounts",
  refund: "Refund",
  lent: "Lent",
  borrowed: "Borrowed",
  repayment_received: "Repayment received",
  repayment_made: "Repayment made",
  reversal: "Reversal",
  unknown: "Type not known",
};

export function typeLabel(type: string): string {
  return TYPE_LABEL[type] ?? type;
}

export const TYPES = Object.keys(TYPE_LABEL);

/** What to call a transaction's category: transfers and similar show their type, not "Uncategorized". */
export function categoryLabel(t: { category: string; txn_type: string }): string {
  const typed = ["transfer", "income", "refund", "lent", "borrowed", "repayment_received", "repayment_made", "reversal"];
  return t.category === "Uncategorized" && typed.includes(t.txn_type) ? typeLabel(t.txn_type) : t.category;
}

/** "1,234.5" or "1234.50" -> 123450n paise; null if it is not a valid amount with at most 2 decimals. */
export function toMinor(text: string): bigint | null {
  const clean = text.replace(/[,\s]/g, "");
  const match = /^(\d{1,13})(?:\.(\d{1,2}))?$/.exec(clean);
  if (!match) return null;
  return BigInt(match[1]!) * 100n + BigInt((match[2] ?? "").padEnd(2, "0"));
}

/** 123450n -> "1234.50" (exact; for sending to the API and for formatting). */
export function fromMinor(minor: bigint): string {
  const sign = minor < 0n ? "-" : "";
  const abs = minor < 0n ? -minor : minor;
  return `${sign}${abs / 100n}.${String(abs % 100n).padStart(2, "0")}`;
}

/** Today's date in the user's time zone, as YYYY-MM-DD. */
export function todayIso(now = new Date()): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
}
