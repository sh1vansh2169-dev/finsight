import { type FormEvent, useState } from "react";

import { useFinishImport, usePreviewImport } from "../api/hooks";
import type { ImportDetail } from "../api/types";
import { Amount, Button, Card, ErrorNote, Notice } from "../components/ui";
import { shortDate } from "../lib/format";
import { InboxHint } from "./Pending";

const OUTCOME: Record<string, { label: string; className: string }> = {
  new: { label: "Will be added", className: "bg-primary-soft text-primary-ink" },
  suspected: { label: "Added, please check", className: "bg-warn-bg text-warn-ink" },
  duplicate: { label: "Already recorded", className: "bg-surface-2 text-muted" },
  rejected: { label: "Can't be read", className: "bg-warn-bg text-warn-ink" },
};

/** Import in two steps: preview everything first, then add it or throw it away. */
export function ImportPanel({ onClose, initial }: { onClose: () => void; initial?: ImportDetail }) {
  const [file, setFile] = useState<File | null>(null);
  const [account, setAccount] = useState("");
  const [dayFirst, setDayFirst] = useState(true);
  const [preview, setPreview] = useState<ImportDetail | null>(initial ?? null);
  const [done, setDone] = useState<string | null>(null);
  const previewing = usePreviewImport();
  const finishing = useFinishImport();

  const onPreview = (event: FormEvent) => {
    event.preventDefault();
    if (!file) return;
    setDone(null);
    previewing.mutate({ file, account: account.trim() || undefined, dayFirst }, { onSuccess: setPreview });
  };

  const finish = (action: "commit" | "discard") => {
    if (!preview) return;
    finishing.mutate({ id: preview.batch.id, action }, {
      onSuccess: (batch) => {
        setDone(action === "commit"
          ? `Added ${batch.inserted_rows} transaction(s) from ${batch.filename}.`
          : `Nothing was added from ${batch.filename}.`);
        setPreview(null);
        setFile(null);
      },
    });
  };

  return (
    <Card title={initial ? "Review a statement" : "Import a statement"} className="mb-6" action={<Button variant="quiet" onClick={onClose}>Close</Button>}>
      {!preview && (
        <form onSubmit={onPreview} className="flex flex-col gap-3">
          <label className="flex flex-col gap-1 text-sm font-medium">
            Statement file from your bank, card or payment app
            <input type="file" accept=".csv,.xlsx,.pdf,text/csv,application/pdf,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" required onChange={(e) => setFile(e.target.files?.[0] ?? null)}
              className="text-sm font-normal" />
          </label>
          <div className="flex flex-wrap gap-3">
            <label className="flex min-w-48 flex-1 flex-col gap-1 text-sm font-medium">
              Account name (if the file has none)
              <input value={account} onChange={(e) => setAccount(e.target.value)} placeholder="e.g. HDFC Savings"
                className="min-h-10 rounded-xl border border-field bg-surface px-3 text-sm font-normal" />
            </label>
            <label className="flex flex-col gap-1 text-sm font-medium">
              Dates like 03/04/2026 mean
              <select value={dayFirst ? "day" : "month"} onChange={(e) => setDayFirst(e.target.value === "day")}
                className="min-h-10 rounded-xl border border-field bg-surface px-3 text-sm font-normal">
                <option value="day">3 April (day first)</option>
                <option value="month">March 4 (month first)</option>
              </select>
            </label>
          </div>
          {previewing.error && <ErrorNote error={previewing.error} />}
          <div><Button type="submit" disabled={!file || previewing.isPending}>{previewing.isPending ? "Reading…" : "Preview"}</Button></div>
          <p className="text-xs text-muted">
            CSV, Excel (.xlsx) or PDF. PDFs must contain text with a transaction table; scanned or password-protected
            PDFs can't be read. Nothing is saved until you choose to add it.
          </p>
          <InboxHint />
        </form>
      )}

      {done && <Notice>{done}</Notice>}

      {preview && (
        <div className="flex flex-col gap-3">
          <p className="text-sm">
            <strong>{preview.batch.filename}</strong>: {preview.batch.new_rows + preview.batch.suspected_rows} to add,{" "}
            {preview.batch.duplicate_rows} already recorded, {preview.batch.rejected_rows} can't be read.
          </p>
          {preview.batch.warnings.map((w) => <Notice key={w} tone="warn">{w}</Notice>)}
          <div className="max-h-96 overflow-auto rounded-xl border border-line">
            <table className="w-full text-left text-sm">
              <thead className="sticky top-0 bg-surface-2 text-xs text-muted">
                <tr><th className="px-3 py-2">Row</th><th className="px-3 py-2">Transaction</th><th className="px-3 py-2">Result</th></tr>
              </thead>
              <tbody className="divide-y divide-line">
                {preview.rows.map((r) => (
                  <tr key={r.source_row} className="align-top">
                    <td className="tabular px-3 py-2 text-muted">{r.source_row}</td>
                    <td className="px-3 py-2">
                      {r.transaction ? (
                        <div className="flex flex-wrap justify-between gap-2">
                          <span>{shortDate(r.transaction.date)} · {r.transaction.description}</span>
                          <Amount value={r.transaction.amount} />
                        </div>
                      ) : (
                        <span className="text-muted">{Object.values(r.raw ?? {}).filter(Boolean).join(" · ") || "(empty)"}</span>
                      )}
                      {r.reason && <p className="mt-1 text-xs text-muted">{r.reason}</p>}
                    </td>
                    <td className="px-3 py-2">
                      <span className={`whitespace-nowrap rounded-full px-2 py-0.5 text-xs ${OUTCOME[r.outcome]?.className}`}>
                        {OUTCOME[r.outcome]?.label}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {finishing.error && <ErrorNote error={finishing.error} />}
          <div className="flex flex-wrap gap-2">
            <Button onClick={() => finish("commit")} disabled={finishing.isPending}>
              Add {preview.batch.new_rows + preview.batch.suspected_rows} transaction(s)
            </Button>
            <Button variant="secondary" onClick={() => finish("discard")} disabled={finishing.isPending}>Don't import</Button>
          </div>
        </div>
      )}
    </Card>
  );
}
