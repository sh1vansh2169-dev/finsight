import { useMutation } from "@tanstack/react-query";
import { Link } from "react-router";

import { ApiError, api } from "../api/client";
import { useCorrectTransaction, useInvalidateLedger } from "../api/hooks";
import { useSuggestions } from "../api/more";
import type { CategorySuggestion } from "../api/types";
import { PageTitle } from "../components/AppShell";
import { Amount, Button, Card, EmptyState, ErrorNote, Loading, Notice } from "../components/ui";
import { shortDate } from "../lib/format";

// A model score is never certainty: never show "100%" or "0%".
export const percent = (p: number) => (p >= 0.995 ? "over 99%" : p < 0.01 ? "under 1%" : `${Math.round(p * 100)}%`);

/** Model suggestions for uncategorised spending. Shown as questions, never as facts. */
export function Suggestions() {
  const suggestions = useSuggestions();
  const invalidate = useInvalidateLedger();
  const applyAll = useMutation({
    mutationFn: (min: number) => api<{ applied: number }>("/ml/category-suggestions/apply", { body: { min_confidence: min } }),
    onSuccess: invalidate,
  });

  const noModel = suggestions.error instanceof ApiError && suggestions.error.status === 404;
  const confident = suggestions.data?.suggestions.filter((s) => s.confidence >= 0.9).length ?? 0;

  return (
    <>
      <PageTitle title="Suggested categories"
        subtitle="Guesses from a model for spending your rules did not recognise. Accept the ones that are right."
        action={<Link to="/transactions" className="text-sm font-medium text-primary-ink underline">Back to transactions</Link>} />
      {suggestions.isPending ? <Loading /> : noModel ? (
        <EmptyState title="No suggestion model yet">Category suggestions need a trained model. Your categories still work without one.</EmptyState>
      ) : suggestions.isError ? <ErrorNote error={suggestions.error} retry={() => suggestions.refetch()} /> : (
        <>
          <div className="mb-4"><Notice>{suggestions.data.note.replace(/; accept one with .*$/, ".")}</Notice></div>
          {applyAll.data && <div className="mb-4"><Notice>Applied {applyAll.data.applied} suggestion(s), marked as suggested so you can tell them apart.</Notice></div>}
          {applyAll.error && <div className="mb-4"><ErrorNote error={applyAll.error} /></div>}
          {suggestions.data.suggestions.length === 0 ? (
            <EmptyState title="Nothing to suggest">Every spending transaction has a category.</EmptyState>
          ) : (
            <Card>
              {confident > 0 && (
                <div className="mb-3 flex flex-wrap items-center justify-between gap-2 rounded-xl bg-surface-2 p-3 text-sm">
                  <span>{confident} suggestion(s) are at least 90% confident.</span>
                  <Button variant="secondary" onClick={() => applyAll.mutate(0.9)} disabled={applyAll.isPending}>
                    Apply those {confident}
                  </Button>
                </div>
              )}
              <ul className="divide-y divide-line">
                {suggestions.data.suggestions.map((s) => <Row key={s.transaction.id} s={s} />)}
              </ul>
            </Card>
          )}
        </>
      )}
    </>
  );
}

function Row({ s }: { s: CategorySuggestion }) {
  const correct = useCorrectTransaction();
  const accept = (category: string) => correct.mutate({ id: s.transaction.id, category });
  return (
    <li className="py-3">
      <div className="flex justify-between gap-3">
        <div className="min-w-0">
          <p className="truncate text-sm font-medium">{s.transaction.description}</p>
          <p className="text-xs text-muted">{shortDate(s.transaction.date)} · {s.transaction.account}</p>
        </div>
        <Amount value={s.transaction.amount} currency={s.transaction.currency} className="shrink-0 text-sm" />
      </div>
      <div className="mt-2 flex flex-wrap items-center gap-2 text-sm">
        <span>Looks like <strong>{s.category}</strong>? <span className="text-xs text-muted">({percent(s.confidence)} sure)</span></span>
        <Button onClick={() => accept(s.category)} disabled={correct.isPending}>Yes, {s.category}</Button>
        {s.alternatives.filter((a) => a.confidence >= 0.05).map((a) => (
          <Button key={a.category} variant="quiet" onClick={() => accept(a.category)} disabled={correct.isPending}>
            {a.category} ({percent(a.confidence)})
          </Button>
        ))}
      </div>
      {correct.error && <div className="mt-2"><ErrorNote error={correct.error} /></div>}
    </li>
  );
}
