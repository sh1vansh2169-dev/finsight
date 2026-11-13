import { type ButtonHTMLAttributes, type ReactNode, useEffect, useState } from "react";

import { basisLabel, isNegative, money, signedMoney } from "../lib/format";

export function Card({ title, action, children, className = "" }: {
  title?: string;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={`glass rounded-[var(--radius-card)] p-5 ${className}`}>
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
  primary: "bg-primary text-on-primary shadow-[0_10px_24px_-12px_var(--primary)] hover:opacity-90",
  secondary: "bg-surface-2 text-ink hover:brightness-95",
  quiet: "text-primary-ink hover:bg-primary-soft",
  danger: "bg-surface-2 text-danger-ink hover:brightness-95",
};

export function Button({ variant = "primary", className = "", ...props }: ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: Variant;
}) {
  return (
    <button
      className={`press inline-flex min-h-11 items-center justify-center gap-2 rounded-full px-5 text-sm font-semibold
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
      className={`rounded-2xl px-4 py-3 text-sm ${tone === "warn" ? "bg-warn-bg text-warn-ink" : "bg-surface-2 text-ink-2"}`}
    >
      {children}
    </div>
  );
}

export function EmptyState({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="rounded-3xl bg-surface-2 px-4 py-10 text-center">
      <p className="font-medium text-ink">{title}</p>
      {children && <div className="mt-1 text-sm text-muted">{children}</div>}
    </div>
  );
}

export function Loading({ label = "Loading" }: { label?: string }) {
  return (
    <div role="status" aria-live="polite" className="animate-pulse rounded-3xl bg-surface-2 px-4 py-6 text-sm text-muted">
      {label}…
    </div>
  );
}

export function ErrorNote({ error, retry }: { error: unknown; retry?: () => void }) {
  const message = error instanceof Error ? error.message : "Something went wrong.";
  return (
    <div role="alert" className="glass flex flex-wrap items-center justify-between gap-3 rounded-2xl px-4 py-3">
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

function reducedMotion(): boolean {
  return window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;
}

/**
 * A money figure that counts up when it first appears. The animation is decoration only:
 * screen readers get the exact figure at once, and the last frame shows the exact string
 * from the server (the in-between numbers are never used for anything).
 */
export function CountUp({ value, currency = "INR", signed = false, duration = 1200 }: {
  value: string;
  currency?: string;
  signed?: boolean;
  duration?: number;
}) {
  const exact = signed ? signedMoney(value, currency) : money(value, currency);
  const [shown, setShown] = useState<string>(() => (reducedMotion() ? exact : money("0", currency)));
  useEffect(() => {
    if (reducedMotion()) {
      setShown(exact);
      return;
    }
    const target = Math.abs(Number(value));
    const sign = signed && Number(value) < 0 ? "\u2212" : signed && Number(value) > 0 ? "+" : "";
    const start = performance.now();
    let frame = 0;
    let done = false;
    // Once the exact figure is shown, nothing may replace it: a late frame (busy device) used to
    // overwrite it with an in-between number.
    const finish = () => {
      done = true;
      cancelAnimationFrame(frame);
      setShown(exact);
    };
    const step = () => {
      if (done) return;
      const t = Math.min(1, (performance.now() - start) / duration);
      if (t >= 1) {
        finish();
        return;
      }
      const eased = 1 - Math.pow(1 - t, 3);
      setShown(sign + money((target * eased).toFixed(2), currency));
      frame = requestAnimationFrame(step);
    };
    frame = requestAnimationFrame(step);
    // Browsers pause animation frames in background tabs: never let the figure stay mid-count.
    const settle = setTimeout(finish, duration + 50);
    return () => {
      done = true;
      cancelAnimationFrame(frame);
      clearTimeout(settle);
    };
  }, [value, currency, signed, duration, exact]);
  return (
    <span className="tabular">
      <span className="sr-only">{exact}</span>
      <span aria-hidden="true">{shown}</span>
    </span>
  );
}
