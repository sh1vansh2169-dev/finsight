import { type FormEvent, useState } from "react";

import { useCategories } from "../api/hooks";
import { useBudgets, useBudgetUsage, useDeleteBudget, useSetBudget } from "../api/more";
import type { Budget, BudgetUse } from "../api/types";
import { Button, Card, EmptyState, ErrorNote, Loading } from "../components/ui";
import { fromMinor, money, toMinor } from "../lib/format";
import { fieldClass } from "./MajraForms";

const STATE_LABEL: Record<BudgetUse["state"], string> = { on_track: "On track", close: "Close to the limit", over: "Over the limit" };

/** Monthly limits per category. Neutral wording: a budget is a plan, not a verdict. */
export function Budgets() {
  const budgets = useBudgets();
  const usage = useBudgetUsage();
  const [editing, setEditing] = useState<Budget | "new" | null>(null);
  const use = new Map(usage.data?.map((u) => [`${u.category}|${u.currency}`, u]));

  return (
    <>
      <div className="mb-4 flex justify-end">
        {!editing && <Button onClick={() => setEditing("new")}>Add budget</Button>}
      </div>
      {editing && (
        <Card title={editing === "new" ? "New monthly budget" : `Budget for ${editing.category}`} className="mb-4">
          <BudgetForm budget={editing === "new" ? undefined : editing} taken={budgets.data?.map((b) => b.category) ?? []}
            onDone={() => setEditing(null)} />
        </Card>
      )}
      {budgets.isPending ? <Loading /> : budgets.isError ? <ErrorNote error={budgets.error} retry={() => budgets.refetch()} /> :
        budgets.data.length === 0 ? (
          <EmptyState title="No budgets yet">Set a monthly limit for a category to see how much is left as the month goes on.</EmptyState>
        ) : (
          <Card>
            <ul className="flex flex-col divide-y divide-line">
              {budgets.data.map((b) => <Row key={b.id} b={b} u={use.get(`${b.category}|${b.currency}`)} onEdit={() => setEditing(b)} />)}
            </ul>
            <p className="mt-3 text-xs text-muted">Spending is this month's recorded spending after refunds, for the newest month with data.</p>
          </Card>
        )}
    </>
  );
}

function Row({ b, u, onEdit }: { b: Budget; u?: BudgetUse; onEdit: () => void }) {
  const remove = useDeleteBudget();
  return (
    <li className="py-3">
      <div className="flex flex-wrap items-baseline justify-between gap-2 text-sm">
        <span className="font-medium">{b.category}</span>
        <span className="tabular text-muted">
          {u ? `${money(u.spent, b.currency)} of ${money(b.monthly_limit, b.currency)}` : `${money(b.monthly_limit, b.currency)} a month`}
        </span>
      </div>
      {u && (
        <>
          <div className="mt-1 h-2 rounded-full bg-surface-2" role="progressbar" aria-valuenow={u.percent_used} aria-valuemin={0}
            aria-valuemax={100} aria-label={`${b.category} budget used`}>
            <div className={`h-2 rounded-full ${u.state === "over" ? "bg-out" : "bg-primary"}`} style={{ width: `${Math.min(u.percent_used, 100)}%` }} />
          </div>
          <p className="mt-1 text-xs text-muted"><span className="font-medium text-ink-2">{STATE_LABEL[u.state]}.</span> {u.message}</p>
        </>
      )}
      <div className="mt-1 flex gap-2">
        <Button variant="quiet" onClick={onEdit}>Change</Button>
        <Button variant="quiet" onClick={() => remove.mutate(b.id)} disabled={remove.isPending} aria-label={`Remove the ${b.category} budget`}>Remove</Button>
      </div>
      {remove.error && <ErrorNote error={remove.error} />}
    </li>
  );
}

function BudgetForm({ budget, taken, onDone }: { budget?: Budget; taken: string[]; onDone: () => void }) {
  const categories = useCategories();
  const [category, setCategory] = useState(budget?.category ?? "");
  const [limit, setLimit] = useState(budget?.monthly_limit ?? "");
  const save = useSetBudget();
  const minor = toMinor(limit);
  const choices = (categories.data ?? []).filter((c) => c !== "Uncategorized" && (c === budget?.category || !taken.includes(c)));
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (minor === null) return;
    save.mutate({ category, monthly_limit: fromMinor(minor) }, { onSuccess: onDone });
  };
  return (
    <form onSubmit={submit} className="flex flex-col gap-3">
      <div className="flex flex-wrap gap-3">
        <label className="flex min-w-48 flex-1 flex-col gap-1 text-sm font-medium">Category
          <select required value={category} onChange={(e) => setCategory(e.target.value)} disabled={!!budget} className={fieldClass}>
            <option value="" disabled>Choose a category</option>
            {choices.map((c) => <option key={c}>{c}</option>)}
          </select>
        </label>
        <label className="flex min-w-48 flex-1 flex-col gap-1 text-sm font-medium">Monthly limit
          <input inputMode="decimal" required value={limit} onChange={(e) => setLimit(e.target.value)} placeholder="0.00"
            aria-invalid={limit !== "" && minor === null} className={`${fieldClass} tabular`} />
        </label>
      </div>
      {save.error && <ErrorNote error={save.error} />}
      <div className="flex gap-2">
        <Button type="submit" disabled={!category || minor === null || minor === 0n || save.isPending}>{save.isPending ? "Saving…" : "Save"}</Button>
        <Button type="button" variant="quiet" onClick={onDone}>Cancel</Button>
      </div>
    </form>
  );
}
