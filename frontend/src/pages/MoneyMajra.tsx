import { useMajraGroup, useMajraGroups, useMajraSummary } from "../api/hooks";
import type { MajraGroup } from "../api/types";
import { PageTitle } from "../components/AppShell";
import { Card, EmptyState, ErrorNote, Loading, Notice } from "../components/ui";
import { money, shortDate } from "../lib/format";

export function MoneyMajra() {
  const summary = useMajraSummary();
  const groups = useMajraGroups();
  return (
    <>
      <PageTitle title="Money Majra" subtitle="Shared costs, money lent and borrowed, and who owes whom." />
      {summary.data?.map((s) => (
        <Card key={s.currency} className="mb-4">
          <dl className="grid grid-cols-2 gap-3">
            <div><dt className="text-sm text-muted">Others owe you</dt><dd className="tabular text-2xl font-semibold">{money(s.owed_to_you, s.currency)}</dd></div>
            <div><dt className="text-sm text-muted">You owe</dt><dd className="tabular text-2xl font-semibold">{money(s.you_owe, s.currency)}</dd></div>
          </dl>
          <p className="mt-2 text-xs text-muted">{s.note}</p>
        </Card>
      ))}
      {groups.isPending ? <Loading /> : groups.isError ? <ErrorNote error={groups.error} retry={() => groups.refetch()} /> :
        groups.data.length === 0 ? (
          <EmptyState title="Nothing here yet">Shared trips, loans and repayments will appear here.</EmptyState>
        ) : (
          <div className="grid gap-4 lg:grid-cols-2">
            {groups.data.map((g) => <Group key={g.id} group={g} />)}
          </div>
        )}
      <p className="mt-6 text-sm text-muted">Adding expenses, loans and repayments from this screen is coming next.</p>
    </>
  );
}

function Group({ group }: { group: MajraGroup }) {
  const detail = useMajraGroup(group.id);
  const c = group.currency;
  return (
    <Card title={group.name}>
      {detail.isPending ? <Loading /> : detail.isError ? <ErrorNote error={detail.error} /> : (
        <>
          {!detail.data.balances_sum_to_zero && <Notice tone="warn">These balances do not add up; please report this.</Notice>}
          <ul className="flex flex-col gap-1 text-sm">
            {detail.data.balances.filter((b) => !b.person.is_me).map((b) => (
              <li key={b.person.id} className="flex justify-between gap-3">
                <span>{b.person.name}</span>
                <span className="tabular text-ink-2">
                  {b.status === "settled" ? "settled" : b.status === "owes" ? `owes ${money(b.balance, c)}` : `is owed ${money(b.balance, c)}`}
                </span>
              </li>
            ))}
          </ul>
          {detail.data.settlement.length > 0 && (
            <div className="mt-3 rounded-xl bg-surface-2 p-3 text-sm">
              <p className="mb-1 font-medium">
                {detail.data.settlement_is_minimal ? "Settle up in the fewest payments" : "One way to settle up"}
              </p>
              <ul>
                {detail.data.settlement.map((t, i) => (
                  <li key={i}>
                    {t.payer.is_me ? "You pay" : `${t.payer.name} pays`} {t.receiver.is_me ? "you" : t.receiver.name}{" "}
                    <strong className="tabular">{money(t.amount, c)}</strong>
                  </li>
                ))}
              </ul>
            </div>
          )}
          <details className="mt-3 text-sm">
            <summary className="cursor-pointer text-primary-ink">History ({detail.data.entries.length})</summary>
            <ul className="mt-2 divide-y divide-line">
              {detail.data.entries.map((e) => (
                <li key={e.id} className={`flex justify-between gap-3 py-1.5 ${e.voided ? "text-muted line-through" : ""}`}>
                  <span>{shortDate(e.date)} · {e.description}</span>
                  <span className="tabular">{money(e.amount, c)}</span>
                </li>
              ))}
            </ul>
          </details>
        </>
      )}
    </Card>
  );
}
