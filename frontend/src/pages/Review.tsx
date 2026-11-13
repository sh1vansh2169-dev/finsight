import { Link } from "react-router";

import { useDuplicates, useReopenDuplicate, useResolveDuplicate, useScanDuplicates } from "../api/more";
import type { DuplicateCandidate, Transaction } from "../api/types";
import { PageTitle } from "../components/AppShell";
import { Amount, Button, Card, EmptyState, ErrorNote, Loading, Notice } from "../components/ui";
import { categoryLabel, shortDate } from "../lib/format";

const DECIDED: Record<string, string> = {
  duplicate: "Same payment: one record kept",
  distinct: "Different payments: both kept",
  superseded: "No longer needed (one record changed)",
};

/** Pairs of records that may be one payment. Nothing is merged unless the user says so. */
export function Review() {
  const open = useDuplicates("open");
  const all = useDuplicates("all");
  const scan = useScanDuplicates();
  const decided = all.data?.filter((c) => c.status !== "open") ?? [];

  return (
    <>
      <PageTitle title="Possible duplicates"
        subtitle="The same payment can arrive twice, for example from a payment app and from your bank. Nothing is merged unless you choose to."
        action={<Link to="/transactions" className="text-sm font-medium text-primary-ink underline">Back to transactions</Link>} />

      <div className="mb-4 flex flex-wrap items-center gap-3">
        <Button variant="secondary" onClick={() => scan.mutate()} disabled={scan.isPending}>
          {scan.isPending ? "Looking…" : "Look for duplicates again"}
        </Button>
        {scan.data && <span className="text-sm text-muted" role="status">Found {scan.data.new_candidates} new pair(s).</span>}
      </div>
      {scan.error && <div className="mb-4"><ErrorNote error={scan.error} /></div>}

      {open.isPending ? <Loading /> : open.isError ? <ErrorNote error={open.error} retry={() => open.refetch()} /> :
        open.data.length === 0 ? (
          <EmptyState title="Nothing to review">No pairs of records look like the same payment.</EmptyState>
        ) : (
          <div className="flex flex-col gap-4">
            <p className="text-sm text-muted" aria-live="polite">{open.data.length} pair(s) to review</p>
            {open.data.map((c) => <Pair key={c.id} candidate={c} />)}
          </div>
        )}

      {decided.length > 0 && (
        <Card title="Decided" className="mt-6">
          <ul className="divide-y divide-line">
            {decided.map((c) => <Decided key={c.id} candidate={c} />)}
          </ul>
        </Card>
      )}
    </>
  );
}

function Record({ t }: { t: Transaction }) {
  return (
    <div className="min-w-0 flex-1 rounded-xl border border-line p-3">
      <div className="flex justify-between gap-3">
        <p className="truncate text-sm font-medium">{t.description}</p>
        <Amount value={t.amount} currency={t.currency} className="shrink-0 text-sm" />
      </div>
      <p className="text-xs text-muted">{shortDate(t.date)} · {t.account} · {categoryLabel(t)}</p>
    </div>
  );
}

function Pair({ candidate }: { candidate: DuplicateCandidate }) {
  const resolve = useResolveDuplicate();
  const [a, b] = candidate.transactions;
  if (!a || !b) return null;
  const pending = resolve.isPending;
  return (
    <Card>
      <p className="mb-2 text-sm">
        <span className={`mr-2 rounded-full px-2 py-0.5 text-xs ${candidate.confidence === "high" ? "bg-warn-bg text-warn-ink" : "bg-surface-2 text-muted"}`}>
          {candidate.confidence === "high" ? "Very likely the same" : "Possibly the same"}
        </span>
        <span className="text-xs text-muted">match score {candidate.score} of 100 (a rule of thumb, not a probability)</span>
      </p>
      <div className="flex flex-col gap-2 sm:flex-row">
        <Record t={a} />
        <Record t={b} />
      </div>
      {candidate.reasons.length > 0 && (
        <ul className="mt-2 list-disc pl-5 text-xs text-muted">
          {candidate.reasons.map((r) => <li key={r}>{r}</li>)}
        </ul>
      )}
      {resolve.error && <div className="mt-2"><ErrorNote error={resolve.error} /></div>}
      <div className="mt-3 flex flex-wrap gap-2">
        <Button onClick={() => resolve.mutate({ id: candidate.id, keep: a.id })} disabled={pending}>Same payment: keep the first</Button>
        <Button onClick={() => resolve.mutate({ id: candidate.id, keep: b.id })} disabled={pending}>Same payment: keep the second</Button>
        <Button variant="secondary" onClick={() => resolve.mutate({ id: candidate.id, keep: null })} disabled={pending}>
          Different payments
        </Button>
      </div>
      <p className="mt-2 text-xs text-muted">The record you don't keep is hidden from totals, not deleted. You can undo this.</p>
    </Card>
  );
}

function Decided({ candidate }: { candidate: DuplicateCandidate }) {
  const reopen = useReopenDuplicate();
  const [a, b] = candidate.transactions;
  return (
    <li className="flex flex-wrap items-center justify-between gap-3 py-2 text-sm">
      <div className="min-w-0">
        <p className="truncate">{a?.description}{b && b.description !== a?.description ? ` / ${b.description}` : ""}</p>
        <p className="text-xs text-muted">{DECIDED[candidate.status]}</p>
      </div>
      {candidate.status !== "superseded" && (
        <Button variant="quiet" onClick={() => reopen.mutate(candidate.id)} disabled={reopen.isPending}>Undo</Button>
      )}
      {reopen.error && <div className="w-full"><Notice tone="warn">{reopen.error.message}</Notice></div>}
    </li>
  );
}
