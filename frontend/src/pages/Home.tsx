import { Link } from "react-router";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { useDashboard } from "../api/hooks";
import type { Dashboard, SeriesPoint } from "../api/types";
import { PageTitle } from "../components/AppShell";
import { Amount, Card, EmptyState, ErrorNote, Loading, Notice } from "../components/ui";
import { categoryLabel, money, monthLabel, shortDate, signedMoney } from "../lib/format";

export function Home() {
  const dashboard = useDashboard();
  if (dashboard.isPending) return <Loading label="Loading your month" />;
  if (dashboard.isError) return <ErrorNote error={dashboard.error} retry={() => dashboard.refetch()} />;
  const d = dashboard.data;

  if (!d.currency || !d.summary) {
    return (
      <>
        <PageTitle title="Welcome to MoneyOS" />
        <EmptyState title="No transactions yet">
          Import a bank or card statement from <Link className="text-primary-ink underline" to="/transactions">Transactions</Link> to see your month here.
        </EmptyState>
      </>
    );
  }
  const c = d.currency;
  return (
    <>
      <PageTitle title={monthLabel(d.month)} subtitle={d.note} />
      <div className="grid gap-4 sm:grid-cols-3">
        <Stat label="Income" value={money(d.summary.income, c)} tone="in" />
        <Stat label="Spending (after refunds)" value={money(d.summary.spending, c)} tone="out" />
        <Stat label="Net cash flow" value={<Amount value={d.summary.net_cash_flow} currency={c} />} />
      </div>

      {d.warnings.length > 0 && (
        <div className="mt-4 flex flex-col gap-2">
          {d.warnings.slice(0, 3).map((w) => <Notice key={w} tone="warn">{w}</Notice>)}
        </div>
      )}

      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <Card title="Daily spending">
          <DailyChart points={d.daily} currency={c} />
        </Card>
        <Outlook d={d} />
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <Card title="Budgets">
          {d.budgets.length === 0 ? (
            <EmptyState title="No budgets yet">Budgets you set will show here with how much is left.</EmptyState>
          ) : (
            <ul className="flex flex-col gap-4">
              {d.budgets.map((b) => (
                <li key={b.category}>
                  <div className="flex justify-between text-sm">
                    <span className="font-medium">{b.category}</span>
                    <span className="tabular text-muted">{money(b.spent, b.currency)} of {money(b.limit, b.currency)}</span>
                  </div>
                  <div className="mt-1 h-2 rounded-full bg-surface-2" role="progressbar" aria-valuenow={b.percent_used}
                    aria-valuemin={0} aria-valuemax={100} aria-label={`${b.category} budget used`}>
                    <div className={`h-2 rounded-full ${b.state === "over" ? "bg-out" : "bg-primary"}`}
                      style={{ width: `${Math.min(b.percent_used, 100)}%` }} />
                  </div>
                  <p className="mt-1 text-xs text-muted">{b.message}</p>
                </li>
              ))}
            </ul>
          )}
        </Card>
        <Card title="Money Majra">
          {d.money_majra ? (
            <>
              <dl className="grid grid-cols-2 gap-3">
                <div><dt className="text-sm text-muted">Others owe you</dt><dd className="tabular text-xl font-semibold">{money(d.money_majra.owed_to_you, c)}</dd></div>
                <div><dt className="text-sm text-muted">You owe</dt><dd className="tabular text-xl font-semibold">{money(d.money_majra.you_owe, c)}</dd></div>
              </dl>
              <p className="mt-2 text-xs text-muted">{d.money_majra.note}</p>
            </>
          ) : (
            <EmptyState title="Nothing shared or lent yet" />
          )}
        </Card>
      </div>

      <Card title="Recent transactions" className="mt-4"
        action={<Link to="/transactions" className="text-sm font-medium text-primary-ink underline">See all</Link>}>
        <ul className="divide-y divide-line">
          {d.recent_transactions.map((t) => (
            <li key={t.id} className="flex items-center justify-between gap-3 py-2">
              <div className="min-w-0">
                <p className="truncate text-sm font-medium">{t.description}</p>
                <p className="text-xs text-muted">{shortDate(t.date)} · {categoryLabel(t)}</p>
              </div>
              <Amount value={t.amount} currency={t.currency} className="shrink-0 text-sm" />
            </li>
          ))}
        </ul>
      </Card>
    </>
  );
}

function Stat({ label, value, tone }: { label: string; value: React.ReactNode; tone?: "in" | "out" }) {
  return (
    <div className="rounded-[var(--radius-card)] border border-line bg-surface p-5">
      <p className="text-sm text-muted">{label}</p>
      <p className={`tabular mt-1 text-2xl font-semibold ${tone === "in" ? "text-accent" : tone === "out" ? "text-out" : ""}`}>{value}</p>
    </div>
  );
}

function DailyChart({ points, currency }: { points: SeriesPoint[]; currency: string }) {
  const unknownDays = points.filter((p) => p.coverage === 0).length;
  const data = points.map((p) => ({
    day: Number(p.period.slice(-2)),
    // Display only: a chart needs numbers. Unknown days stay empty, never 0.
    spending: p.spending === null ? null : Math.max(Number(p.spending), 0),
    known: p.coverage > 0,
  }));
  return (
    <>
      <div className="h-48" role="img" aria-label="Bar chart of spending per day this month">
        <ResponsiveContainer width="100%" height="100%" minWidth={200}>
          <BarChart data={data} margin={{ left: -10, right: 4, top: 4, bottom: 0 }}>
            <CartesianGrid vertical={false} stroke="var(--chart-grid)" />
            <XAxis dataKey="day" tickLine={false} axisLine={false} tick={{ fill: "var(--muted)", fontSize: 11 }} interval={4} />
            <YAxis tickLine={false} axisLine={false} tick={{ fill: "var(--muted)", fontSize: 11 }} width={56}
              tickFormatter={(v: number) => (v >= 1000 ? `${Math.round(v / 1000)}k` : String(v))} />
            <Tooltip cursor={{ fill: "var(--surface-2)" }}
              contentStyle={{ background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 12, color: "var(--ink)" }}
              formatter={(v) => (v === null || v === undefined ? "No statement: unknown" : money(String(v), currency))}
              labelFormatter={(day) => `Day ${day}`} />
            <Bar dataKey="spending" fill="var(--chart-out)" radius={[4, 4, 0, 0]} maxBarSize={14} name="Spending" />
          </BarChart>
        </ResponsiveContainer>
      </div>
      {unknownDays > 0 && (
        <p className="mt-2 text-xs text-muted">No statement covers {unknownDays} day(s) this month; they are shown as gaps, not as zero.</p>
      )}
    </>
  );
}

function Outlook({ d }: { d: Dashboard }) {
  const o = d.outlook;
  if (!o || !d.currency) return null;
  const c = d.currency;
  const range = o.net_change.cautious && o.net_change.hopeful;
  return (
    <Card title="Next 30 days (estimate)">
      <p className="tabular text-2xl font-semibold"><Amount value={o.net_change.estimate} currency={c} /></p>
      <p className="mt-1 text-sm text-muted">
        {range
          ? `Change over the period, from your commitments and usual spending. Range from your own past spending: ${signedMoney(o.net_change.cautious!, c)} to ${signedMoney(o.net_change.hopeful!, c)}.`
          : "Change over the period, from your commitments and usual spending; not enough history for a range yet."}
      </p>
      {o.occurrences.length > 0 && (
        <ul className="mt-3 divide-y divide-line">
          {o.occurrences.slice(0, 4).map((x) => (
            <li key={`${x.date}-${x.name}`} className="flex justify-between gap-3 py-1.5 text-sm">
              <span className="truncate">{shortDate(x.date)} · {x.name}</span>
              <Amount value={x.amount} currency={c} className="shrink-0" />
            </li>
          ))}
        </ul>
      )}
      <p className="mt-3 text-sm">Keep aside for commitments: <strong className="tabular">{money(o.reserve_for_commitments, c)}</strong></p>
      {!/^0+(\.0+)?$/.test(o.not_included.if_others_repay_you) && (
        <p className="mt-1 text-xs text-muted">
          Not counted: {money(o.not_included.if_others_repay_you, c)} that others owe you.
        </p>
      )}
    </Card>
  );
}
