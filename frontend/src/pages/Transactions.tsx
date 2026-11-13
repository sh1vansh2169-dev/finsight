import { useEffect, useState } from "react";
import { Link } from "react-router";

import { useAccounts, useCategories, useCorrectTransaction, useTransactions, type TransactionFilters } from "../api/hooks";
import { useDuplicates, useSuggestions } from "../api/more";
import type { Transaction } from "../api/types";
import { PageTitle } from "../components/AppShell";
import { Icon } from "../components/Icon";
import { Amount, BasisBadge, Button, Card, EmptyState, ErrorNote, Loading } from "../components/ui";
import { basisLabel, categoryLabel, shortDate, typeLabel } from "../lib/format";
import { ImportPanel } from "./ImportPanel";

const PAGE = 50;
// Types each direction can have (mirrors the API's rule; the API checks it too).
const TYPES_FOR = {
  debit: ["expense", "transfer", "lent", "repayment_made", "reversal", "unknown"],
  credit: ["income", "refund", "transfer", "borrowed", "repayment_received", "reversal", "unknown"],
} as const;

function useDebounced<T>(value: T, ms = 300): T {
  const [settled, setSettled] = useState(value);
  useEffect(() => {
    const timer = setTimeout(() => setSettled(value), ms);
    return () => clearTimeout(timer);
  }, [value, ms]);
  return settled;
}

const selectClass = "min-h-10 rounded-xl border border-field bg-surface px-3 text-sm";

export function Transactions() {
  const [text, setText] = useState("");
  const [filters, setFilters] = useState<TransactionFilters>({});
  const [limit, setLimit] = useState(PAGE);
  const [importing, setImporting] = useState(false);
  const q = useDebounced(text.trim());
  const active = { ...filters, q: q || undefined };
  const page = useTransactions(active, limit);
  const categories = useCategories();
  const accounts = useAccounts();
  const duplicates = useDuplicates("open");
  const suggestions = useSuggestions();
  const possibleDuplicates = new Set(duplicates.data?.flatMap((c) => c.transactions.map((t) => t.id)) ?? []);
  const toReview = duplicates.data?.length ?? 0;
  const toCategorise = suggestions.data?.suggestions.length ?? 0;

  const set = (key: keyof TransactionFilters, value: string) => {
    setFilters((f) => ({ ...f, [key]: value || undefined }));
    setLimit(PAGE);
  };

  return (
    <>
      <PageTitle title="Transactions"
        action={<Button onClick={() => setImporting((v) => !v)} aria-expanded={importing}><Icon name="upload" className="h-4 w-4" />Import statement</Button>} />
      {importing && <ImportPanel onClose={() => setImporting(false)} />}

      {(toReview > 0 || toCategorise > 0) && (
        <nav aria-label="Needs your attention" className="mb-4 flex flex-wrap gap-2">
          {toReview > 0 && (
            <Link to="/transactions/review" className="rounded-full bg-warn-bg px-3 py-1.5 text-sm font-medium text-warn-ink">
              {toReview} possible duplicate(s) to review
            </Link>
          )}
          {toCategorise > 0 && (
            <Link to="/transactions/suggestions" className="rounded-full bg-primary-soft px-3 py-1.5 text-sm font-medium text-primary-ink">
              {toCategorise} suggested categor{toCategorise === 1 ? "y" : "ies"}
            </Link>
          )}
        </nav>
      )}

      <div className="mb-4 flex flex-wrap gap-2" role="search">
        <input type="search" placeholder="Search descriptions" aria-label="Search descriptions" value={text}
          onChange={(e) => { setText(e.target.value); setLimit(PAGE); }}
          className="min-h-10 min-w-0 flex-1 rounded-xl border border-field bg-surface px-3 text-sm" />
        <select aria-label="Category" className={selectClass} value={filters.category ?? ""} onChange={(e) => set("category", e.target.value)}>
          <option value="">All categories</option>
          {categories.data?.map((c) => <option key={c}>{c}</option>)}
        </select>
        <select aria-label="Account" className={selectClass} value={filters.account ?? ""} onChange={(e) => set("account", e.target.value)}>
          <option value="">All accounts</option>
          {accounts.data?.map((a) => <option key={a.id}>{a.name}</option>)}
        </select>
        <select aria-label="Type" className={selectClass} value={filters.txn_type ?? ""} onChange={(e) => set("txn_type", e.target.value)}>
          <option value="">All types</option>
          {[...new Set([...TYPES_FOR.debit, ...TYPES_FOR.credit])].map((t) => <option key={t} value={t}>{typeLabel(t)}</option>)}
        </select>
      </div>

      {page.isPending ? <Loading label="Loading transactions" /> : page.isError ? (
        <ErrorNote error={page.error} retry={() => page.refetch()} />
      ) : page.data.total === 0 ? (
        <EmptyState title={q || Object.values(filters).some(Boolean) ? "Nothing matches" : "No transactions yet"}>
          {q || Object.values(filters).some(Boolean) ? "Try a different search or filter." : "Import a statement to get started."}
        </EmptyState>
      ) : (
        <Card>
          <p className="mb-2 text-sm text-muted" aria-live="polite">{page.data.total} transaction(s)</p>
          <ul className="divide-y divide-line">
            {page.data.items.map((t) => <Row key={t.id} t={t} categories={categories.data ?? []} maybeDuplicate={possibleDuplicates.has(t.id)} />)}
          </ul>
          {page.data.items.length < page.data.total && (
            <div className="mt-4 text-center">
              <Button variant="secondary" onClick={() => setLimit((l) => l + PAGE)} disabled={page.isFetching}>
                {page.isFetching ? "Loading…" : "Show more"}
              </Button>
            </div>
          )}
        </Card>
      )}
    </>
  );
}

function Row({ t, categories, maybeDuplicate }: { t: Transaction; categories: string[]; maybeDuplicate: boolean }) {
  const [open, setOpen] = useState(false);
  return (
    <li className="py-2">
      <button type="button" onClick={() => setOpen((v) => !v)} aria-expanded={open}
        className="flex w-full items-center justify-between gap-3 rounded-lg px-1 text-left hover:bg-surface-2">
        <div className="min-w-0 py-1">
          <p className="truncate text-sm font-medium">{t.description}</p>
          <p className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted">
            <span>{shortDate(t.date)}</span><span>·</span><span>{t.account}</span><span>·</span>
            <span>{categoryLabel(t)}</span><BasisBadge basis={t.category === "Uncategorized" ? t.type_basis : t.category_basis} />
            {t.status === "failed" && <span className="font-medium text-danger-ink">Failed: not counted</span>}
            {maybeDuplicate && <span className="rounded-full bg-warn-bg px-2 text-warn-ink">Possible duplicate</span>}
          </p>
        </div>
        <Amount value={t.amount} currency={t.currency} className="shrink-0 text-sm" />
      </button>
      {open && maybeDuplicate && (
        <p className="mt-2 text-xs">
          This may be the same payment as another record. <Link to="/transactions/review" className="font-medium text-primary-ink underline">Review it</Link>
        </p>
      )}
      {open && <Editor t={t} categories={categories} onDone={() => setOpen(false)} />}
    </li>
  );
}

function Editor({ t, categories, onDone }: { t: Transaction; categories: string[]; onDone: () => void }) {
  const [category, setCategory] = useState(t.category);
  const [type, setType] = useState<string>(t.txn_type);
  const correct = useCorrectTransaction();
  const changed = category !== t.category || type !== t.txn_type;
  const save = () =>
    correct.mutate(
      { id: t.id, ...(category !== t.category && { category }), ...(type !== t.txn_type && { txn_type: type }) },
      { onSuccess: onDone },
    );
  return (
    <div className="mt-2 rounded-xl bg-surface-2 p-3">
      <p className="mb-2 text-xs text-muted">
        Type: {typeLabel(t.txn_type)}{t.type_basis !== "none" && ` (${basisLabel(t.type_basis).toLowerCase()})`}.
        {" "}Your changes are saved as yours and kept in the history.
      </p>
      <div className="flex flex-wrap items-end gap-2">
        <label className="flex flex-col gap-1 text-xs font-medium">Category
          <select className={selectClass} value={category} onChange={(e) => setCategory(e.target.value)}>
            {[...new Set([t.category, ...categories])].map((c) => <option key={c}>{c}</option>)}
          </select>
        </label>
        <label className="flex flex-col gap-1 text-xs font-medium">Type
          <select className={selectClass} value={type} onChange={(e) => setType(e.target.value)}>
            {TYPES_FOR[t.direction].map((x) => <option key={x} value={x}>{typeLabel(x)}</option>)}
          </select>
        </label>
        <Button onClick={save} disabled={!changed || correct.isPending}>{correct.isPending ? "Saving…" : "Save"}</Button>
        <Button variant="quiet" onClick={onDone}>Cancel</Button>
      </div>
      {correct.error && <div className="mt-2"><ErrorNote error={correct.error} /></div>}
    </div>
  );
}
