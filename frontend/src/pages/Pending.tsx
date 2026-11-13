import { useState } from "react";

import { useImportDetail, useInboxStatus, usePendingImports } from "../api/more";
import { Button, ErrorNote, Loading } from "../components/ui";
import { shortDate } from "../lib/format";
import { ImportPanel } from "./ImportPanel";

/** Statements staged by the inbox (or unfinished uploads), each waiting for "add" or "don't import". */
export function PendingStatements() {
  const pending = usePendingImports();
  const [open, setOpen] = useState<number | null>(null);
  const detail = useImportDetail(open);
  const batches = pending.data ?? [];
  if (batches.length === 0 && open === null) return null;

  return (
    <section aria-label="Statements waiting for review" className="mb-4">
      {open !== null ? (
        detail.isPending ? <Loading label="Opening the statement" /> : detail.isError ? <ErrorNote error={detail.error} /> : (
          <ImportPanel key={open} initial={detail.data} onClose={() => setOpen(null)} />
        )
      ) : (
        <div className="rounded-xl bg-primary-soft p-3 text-sm text-primary-ink">
          <p className="mb-2 font-medium">{batches.length} statement(s) waiting for your review</p>
          <ul className="flex flex-col gap-1">
            {batches.map((b) => (
              <li key={b.id} className="flex flex-wrap items-center justify-between gap-2">
                <span>{b.filename} · {b.new_rows + b.suspected_rows} to add{b.created_at ? ` · ${shortDate(b.created_at.slice(0, 10))}` : ""}</span>
                <Button variant="secondary" onClick={() => setOpen(b.id)} aria-label={`Review ${b.filename}`}>Review</Button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}

/** Where the inbox folder is, shown in the import panel when the inbox is on. */
export function InboxHint() {
  const inbox = useInboxStatus();
  if (!inbox.data?.enabled) return null;
  return (
    <p className="text-xs text-muted">
      Or save statements into <code className="rounded bg-surface-2 px-1">{inbox.data.folder}</code> (use a subfolder
      named after the account if you like). They appear here for review on their own.
      {inbox.data.note && <span className="block text-warn-ink">Inbox: {inbox.data.note}</span>}
    </p>
  );
}
