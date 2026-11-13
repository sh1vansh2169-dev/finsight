import { NavLink, Outlet } from "react-router";

import { useDashboard, useRecommendations, useUnusual } from "../api/hooks";
import { useDismissUnusual } from "../api/more";
import type { UnusualPayment } from "../api/types";
import { PageTitle } from "../components/AppShell";
import { Amount, Button, Card, EmptyState, ErrorNote, Loading } from "../components/ui";
import { money, shortDate } from "../lib/format";

const TABS = [
  { to: "/insights", label: "Overview", end: true },
  { to: "/insights/budgets", label: "Budgets", end: false },
  { to: "/insights/bills", label: "Bills & income", end: false },
  { to: "/insights/what-if", label: "What if", end: false },
];

/** Insights and planning, as tabs. */
export function Insights() {
  return (
    <>
      <PageTitle title="Insights" subtitle="Patterns in your recorded money, and plans for what comes next. Suggestions only; nothing happens automatically." />
      <nav aria-label="Insights sections" className="mb-5 flex gap-1 overflow-x-auto border-b border-line">
        {TABS.map((t) => (
          <NavLink key={t.to} to={t.to} end={t.end}
            className={({ isActive }) =>
              `whitespace-nowrap border-b-2 px-3 py-2 text-sm font-medium ${isActive ? "border-primary text-primary-ink" : "border-transparent text-muted hover:text-ink"}`}>
            {t.label}
          </NavLink>
        ))}
      </nav>
      <Outlet />
    </>
  );
}

export function InsightsOverview() {
  const recommendations = useRecommendations();
  const unusual = useUnusual();
  const dashboard = useDashboard();
  return (
    <>
      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Suggestions">
          {recommendations.isPending ? <Loading /> : recommendations.isError ? <ErrorNote error={recommendations.error} /> :
            recommendations.data.length === 0 ? <EmptyState title="Nothing to suggest right now" /> : (
              <ul className="flex flex-col gap-3">
                {recommendations.data.map((r) => (
                  <li key={`${r.kind}-${r.title}`} className="rounded-xl bg-surface-2 p-3">
                    <p className="text-sm font-medium">{r.title}</p>
                    <p className="mt-1 text-sm text-ink-2">{r.message}</p>
                  </li>
                ))}
              </ul>
            )}
        </Card>
        <Card title="Unusual payments">
          {unusual.isPending ? <Loading /> : unusual.isError ? <ErrorNote error={unusual.error} /> : (
            <>
              <p className="mb-3 text-xs text-muted">{unusual.data.note}</p>
              {unusual.data.payments.length === 0 ? <EmptyState title="Nothing unusual" /> : (
                <ul className="divide-y divide-line">
                  {unusual.data.payments.map((u) => <Unusual key={u.transaction.id} u={u} />)}
                </ul>
              )}
            </>
          )}
        </Card>
      </div>
      <Card title="Where the money went this month" className="mt-4">
        {dashboard.isPending ? <Loading /> : dashboard.isError ? <ErrorNote error={dashboard.error} /> : (
          <CategoryBars data={dashboard.data.summary?.spending_by_category ?? {}} currency={dashboard.data.currency ?? "INR"} />
        )}
      </Card>
    </>
  );
}

function Unusual({ u }: { u: UnusualPayment }) {
  const dismiss = useDismissUnusual();
  return (
    <li className="py-2">
      <div className="flex justify-between gap-3 text-sm">
        <span className="truncate font-medium">{u.transaction.description}</span>
        <Amount value={u.transaction.amount} currency={u.transaction.currency} />
      </div>
      <p className="text-xs text-muted">{shortDate(u.transaction.date)} · {u.reason}</p>
      <div className="mt-1">
        <Button variant="quiet" onClick={() => dismiss.mutate({ id: u.transaction.id })} disabled={dismiss.isPending}
          aria-label={`${u.transaction.description}: this was expected`}>
          This was expected
        </Button>
      </div>
      {dismiss.error && <ErrorNote error={dismiss.error} />}
    </li>
  );
}

function CategoryBars({ data, currency }: { data: Record<string, string>; currency: string }) {
  const rows = Object.entries(data).filter(([, v]) => !v.startsWith("-"));
  if (rows.length === 0) return <EmptyState title="No spending recorded this month" />;
  // Widths are for drawing only; the amounts shown are the exact strings.
  const max = Math.max(...rows.map(([, v]) => Number(v)));
  return (
    <ul className="flex flex-col gap-2">
      {rows.map(([category, value]) => (
        <li key={category} className="grid grid-cols-[8rem_1fr_auto] items-center gap-3 text-sm">
          <span className="truncate">{category}</span>
          <span className="h-2.5 rounded-full bg-surface-2" aria-hidden="true">
            <span className="block h-2.5 rounded-full bg-primary" style={{ width: `${(Number(value) / max) * 100}%` }} />
          </span>
          <span className="tabular text-ink-2">{money(value, currency)}</span>
        </li>
      ))}
    </ul>
  );
}
