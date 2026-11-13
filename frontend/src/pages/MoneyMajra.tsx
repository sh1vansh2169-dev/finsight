import { useState } from "react";

import { useMajraGroup, useMajraGroups, useMajraPeople, useMajraSummary } from "../api/hooks";
import type { MajraGroup, MajraPerson } from "../api/types";
import { PageTitle } from "../components/AppShell";
import { Button, Card, EmptyState, ErrorNote, Loading, Notice } from "../components/ui";
import { money, shortDate } from "../lib/format";
import {
  AddPersonForm, ExpenseForm, LoanForm, NewGroupForm, PaymentForm, type PaymentDraft, personName, VoidEntry,
} from "./MajraForms";

type PageForm = "person" | "group" | "loan" | null;

export function MoneyMajra() {
  const summary = useMajraSummary();
  const groups = useMajraGroups();
  const people = useMajraPeople();
  const [form, setForm] = useState<PageForm>(null);
  const toggle = (f: PageForm) => setForm((current) => (current === f ? null : f));

  return (
    <>
      <PageTitle title="Money Majra" subtitle="Shared costs, money lent and borrowed, and who owes whom."
        action={
          <div className="flex flex-wrap gap-2">
            <Button variant="secondary" aria-expanded={form === "person"} onClick={() => toggle("person")}>Add person</Button>
            <Button variant="secondary" aria-expanded={form === "group"} onClick={() => toggle("group")}>New group</Button>
            <Button aria-expanded={form === "loan"} onClick={() => toggle("loan")}>Lend or borrow</Button>
          </div>
        } />

      {form && (
        <Card className="mb-4" title={form === "person" ? "Add a person" : form === "group" ? "New group" : "Money lent or borrowed"}>
          {people.isPending ? <Loading /> : people.isError ? <ErrorNote error={people.error} retry={() => people.refetch()} /> :
            form === "person" ? <AddPersonForm onDone={() => setForm(null)} /> :
            form === "group" ? <NewGroupForm people={people.data} onDone={() => setForm(null)} /> :
            <LoanForm people={people.data} onDone={() => setForm(null)} />}
        </Card>
      )}

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
          <EmptyState title="Nothing here yet">
            Add the people you share costs with, then create a group for a trip or a flat, or record money you lent or borrowed.
          </EmptyState>
        ) : (
          <div className="grid gap-4 lg:grid-cols-2">
            {groups.data.map((g) => <Group key={g.id} group={g} />)}
          </div>
        )}
    </>
  );
}

type GroupForm = { kind: "expense" } | { kind: "payment"; draft?: PaymentDraft } | null;

function balanceText(status: string, amount: string, currency: string): string {
  if (status === "settled") return "settled";
  return status === "owes" ? `owes ${money(amount, currency)}` : `is owed ${money(amount, currency)}`;
}

function Group({ group }: { group: MajraGroup }) {
  const detail = useMajraGroup(group.id);
  const [form, setForm] = useState<GroupForm>(null);
  const c = group.currency;
  const names = new Map<number, MajraPerson>(group.members.map((m) => [m.id, m]));

  return (
    <Card title={group.name}
      action={!form && (
        <div className="flex gap-2">
          {group.kind === "group" && <Button variant="secondary" onClick={() => setForm({ kind: "expense" })}>Add expense</Button>}
          <Button variant="secondary" onClick={() => setForm({ kind: "payment" })}>Record payment</Button>
        </div>
      )}>
      {form?.kind === "expense" && (
        <div className="mb-4 rounded-xl border border-line p-3">
          <ExpenseForm group={group} onDone={() => setForm(null)} />
        </div>
      )}
      {form?.kind === "payment" && (
        <div className="mb-4 rounded-xl border border-line p-3">
          <PaymentForm key={JSON.stringify(form.draft ?? {})} group={group} draft={form.draft} onDone={() => setForm(null)} />
        </div>
      )}

      {detail.isPending ? <Loading /> : detail.isError ? <ErrorNote error={detail.error} /> : (
        <>
          {!detail.data.balances_sum_to_zero && <Notice tone="warn">These balances do not add up; please report this.</Notice>}
          <ul className="flex flex-col gap-1 text-sm">
            {detail.data.balances.filter((b) => !b.person.is_me).map((b) => (
              <li key={b.person.id} className="flex justify-between gap-3">
                <span>{b.person.name}</span>
                <span className="tabular text-ink-2">{balanceText(b.status, b.balance, c)}</span>
              </li>
            ))}
          </ul>
          {detail.data.settlement.length > 0 && (
            <div className="mt-3 rounded-xl bg-surface-2 p-3 text-sm">
              <p className="mb-1 font-medium">
                {detail.data.settlement_is_minimal ? "Settle up in the fewest payments" : "One way to settle up"}
              </p>
              <ul className="flex flex-col gap-1">
                {detail.data.settlement.map((t) => (
                  <li key={`${t.payer.id}-${t.receiver.id}`} className="flex flex-wrap items-center justify-between gap-2">
                    <span>
                      {t.payer.is_me ? "You pay" : `${t.payer.name} pays`} {t.receiver.is_me ? "you" : t.receiver.name}{" "}
                      <strong className="tabular">{money(t.amount, c)}</strong>
                    </span>
                    <button type="button" className="text-xs font-medium text-primary-ink underline"
                      onClick={() => setForm({ kind: "payment", draft: { payer_id: t.payer.id, receiver_id: t.receiver.id, amount: t.amount } })}>
                      Record as paid
                    </button>
                  </li>
                ))}
              </ul>
              <p className="mt-2 text-xs text-muted">A suggestion only. Record a payment once it has actually been made.</p>
            </div>
          )}
          <details className="mt-3 text-sm">
            <summary className="cursor-pointer text-primary-ink">History ({detail.data.entries.length})</summary>
            <ul className="mt-2 divide-y divide-line">
              {detail.data.entries.map((e) => (
                <li key={e.id} className="py-2">
                  <div className={`flex justify-between gap-3 ${e.voided ? "text-muted line-through" : ""}`}>
                    <span>
                      {shortDate(e.date)} · {e.description}
                      <span className="block text-xs text-muted">
                        {e.kind === "payment"
                          ? `${personName(names.get(e.paid_by_id)!)} paid ${e.paid_to_id ? (names.get(e.paid_to_id)!.is_me ? "you" : names.get(e.paid_to_id)!.name) : ""}`
                          : `Paid by ${personName(names.get(e.paid_by_id)!)}`}
                      </span>
                    </span>
                    <span className="tabular">{money(e.amount, c)}</span>
                  </div>
                  {e.voided ? <p className="text-xs text-muted">Cancelled: {e.void_reason}</p> : <VoidEntry entry={e} />}
                </li>
              ))}
            </ul>
          </details>
        </>
      )}
    </Card>
  );
}
