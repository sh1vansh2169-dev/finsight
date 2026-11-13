import type { ButtonHTMLAttributes, ReactNode } from "react";

import { basisLabel, isNegative, signedMoney } from "../lib/format";

export function Card({ title, action, children, className = "" }: {
  title?: string;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={`rounded-[var(--radius-card)] border border-line bg-surface p-5 ${className}`}>
      {(title || action) && (
        <div className="mb-3 flex items-center justify-between gap-3">
          {title && <h2 className="text-base font-semibold text-ink">{title}</h2>}
          {action}
        </div>
      )}
      {children}
    </section>
  );
}

type Variant = "primary" | "secondary" | "quiet" | "danger";
const VARIANTS: Record<Variant, string> = {
  primary: "bg-primary text-on-primary hover:opacity-90",
  secondary: "border border-line bg-surface text-ink hover:bg-surface-2",
  quiet: "text-primary-ink hover:bg-primary-soft",
  danger: "border border-line bg-surface text-danger-ink hover:bg-surface-2",
};

export function Button({ variant = "primary", className = "", ...props }: ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: Variant;
}) {
  return (
    <button
      className={`inline-flex min-h-10 items-center justify-center gap-2 rounded-xl px-4 text-sm font-medium transition
        focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary
        disabled:cursor-not-allowed disabled:opacity-50 ${VARIANTS[variant]} ${className}`}
      {...props}
    />
  );
}

/** A signed amount: blue with + for money in, terracotta with − for money out. Never colour alone. */
export function Amount({ value, currency = "INR", className = "" }: { value: string; currency?: string; className?: string }) {
  const out = isNegative(value);
  return (
    <span className={`tabular font-medium ${out ? "text-out" : "text-accent"} ${className}`}>
      <span className="sr-only">{out ? "money out " : "money in "}</span>
      {signedMoney(value, currency)}
    </span>
  );
}

/** Shows where a value came from, so inferred values never look like facts. */
export function BasisBadge({ basis }: { basis: string }) {
  const confirmed = basis === "user" || basis === "source";
  return (
    <span
      className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs ${
        confirmed ? "bg-primary-soft text-primary-ink" : "border border-dashed border-line text-muted"
      }`}
      title={confirmed ? "Confirmed" : "Not confirmed: you can change it"}
    >
      {basisLabel(basis)}
    </span>
  );
}

export function Notice({ tone = "info", children }: { tone?: "info" | "warn"; children: ReactNode }) {
  return (
    <div
      role={tone === "warn" ? "status" : undefined}
      className={`rounded-xl px-4 py-3 text-sm ${tone === "warn" ? "bg-warn-bg text-warn-ink" : "bg-surface-2 text-ink-2"}`}
    >
      {children}
    </div>
  );
}

export function EmptyState({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="rounded-xl border border-dashed border-line px-4 py-8 text-center">
      <p className="font-medium text-ink">{title}</p>
      {children && <div className="mt-1 text-sm text-muted">{children}</div>}
    </div>
  );
}

export function Loading({ label = "Loading" }: { label?: string }) {
  return (
    <div role="status" aria-live="polite" className="animate-pulse rounded-xl bg-surface-2 px-4 py-6 text-sm text-muted">
      {label}…
    </div>
  );
}

export function ErrorNote({ error, retry }: { error: unknown; retry?: () => void }) {
  const message = error instanceof Error ? error.message : "Something went wrong.";
  return (
    <div role="alert" className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-line bg-surface px-4 py-3">
      <span className="text-sm text-danger-ink">{message}</span>
      {retry && <Button variant="secondary" onClick={retry}>Try again</Button>}
    </div>
  );
}

export function SampleBanner() {
  return (
    <div className="bg-warn-bg px-4 py-2 text-center text-sm font-medium text-warn-ink">
      Sample data: everything here is invented for demonstration.
    </div>
  );
}
