import { type FormEvent, useState } from "react";

import {
  useAddCommitment, useCommitments, useConfirmRecurring, useRecurring, useUpcoming, useUpdateCommitment,
} from "../api/more";
import type { Commitment, Recurring } from "../api/types";
import { Amount, Button, Card, EmptyState, ErrorNote, Loading } from "../components/ui";
import { fromMinor, money, shortDate, toMinor, todayIso } from "../lib/format";
import { fieldClass } from "./MajraForms";

const CADENCE: Record<string, string> = {
  once: "once", weekly: "every week", monthly: "every month", quarterly: "every 3 months", yearly: "every year",
};
const cadenceLabel = (c: string) => CADENCE[c] ?? c;

/** Regular payments: what is coming up, what you've confirmed, and what looks regular. */
export function Bills() {
  const [adding, setAdding] = useState(false);
  return (
    <div className="flex flex-col gap-4">
      <UpcomingCard />
      <Card title="Your commitments" action={!adding && <Button variant="secondary" onClick={() => setAdding(true)}>Add your own</Button>}>
        {adding && <div className="mb-4 rounded-xl border border-line p-3"><CommitmentForm onDone={() => setAdding(false)} /></div>}
        <CommitmentList />
      </Card>
      <DetectedCard />
    </div>
  );
}

function UpcomingCard() {
  const upcoming = useUpcoming(30);
  return (
    <Card title="Next 30 days">
      {upcoming.isPending ? <Loading /> : upcoming.isError ? <ErrorNote error={upcoming.error} /> :
        upcoming.data.occurrences.length === 0 ? (
          <EmptyState title="Nothing due">Confirmed commitments due in the next 30 days will show here.</EmptyState>
        ) : (
          <>
            <ul className="divide-y divide-line">
              {upcoming.data.occurrences.map((o) => (
                <li key={`${o.date}-${o.name}`} className="flex justify-between gap-3 py-1.5 text-sm">
                  <span className="truncate">{shortDate(o.date)} · {o.name}</span>
                  <span className="shrink-0 text-right">
                    <Amount value={o.amount} currency={upcoming.data.currency ?? "INR"} />
                    {o.up_to && <span className="block text-xs text-muted">up to {money(o.up_to, upcoming.data.currency ?? "INR")}</span>}
                  </span>
                </li>
              ))}
            </ul>
            <p className="mt-3 text-sm">
              Keep aside for these: <strong className="tabular">{money(upcoming.data.reserve, upcoming.data.currency ?? "INR")}</strong>
            </p>
            <p className="text-xs text-muted">Uses the highest recent amount for bills that vary. Expected income is not subtracted.</p>
          </>
        )}
    </Card>
  );
}

function CommitmentList() {
  const commitments = useCommitments();
  if (commitments.isPending) return <Loading />;
  if (commitments.isError) return <ErrorNote error={commitments.error} retry={() => commitments.refetch()} />;
  const shown = commitments.data.filter((c) => c.status !== "ended");
  if (shown.length === 0) {
    return <EmptyState title="No commitments yet">Confirm a regular payment below, or add one yourself, such as rent or a subscription.</EmptyState>;
  }
  return <ul className="divide-y divide-line">{shown.map((c) => <CommitmentRow key={c.id} c={c} />)}</ul>;
}

function CommitmentRow({ c }: { c: Commitment }) {
  const update = useUpdateCommitment();
  const signed = c.direction === "debit" ? `-${c.amount}` : c.amount;
  return (
    <li className={`py-2 ${c.status === "paused" ? "opacity-70" : ""}`}>
      <div className="flex justify-between gap-3 text-sm">
        <span className="min-w-0">
          <span className="font-medium">{c.name}</span>
          <span className="block text-xs text-muted">
            {cadenceLabel(c.cadence)} · next {shortDate(c.next_due)} · {c.category}
            {c.amount_varies && c.high && ` · varies, up to ${money(c.high, c.currency)}`}
            {c.status === "paused" && " · paused"}
          </span>
        </span>
        <Amount value={signed} currency={c.currency} className="shrink-0" />
      </div>
      <div className="mt-1 flex gap-2">
        {c.status === "active"
          ? <Button variant="quiet" onClick={() => update.mutate({ id: c.id, status: "paused" })} disabled={update.isPending}>Pause</Button>
          : <Button variant="quiet" onClick={() => update.mutate({ id: c.id, status: "active" })} disabled={update.isPending}>Resume</Button>}
        <Button variant="quiet" onClick={() => update.mutate({ id: c.id, status: "ended" })} disabled={update.isPending}
          aria-label={`${c.name} has ended`}>It has ended</Button>
      </div>
      {update.error && <ErrorNote error={update.error} />}
    </li>
  );
}

function DetectedCard() {
  const recurring = useRecurring();
  const suggestions = recurring.data?.filter((r) => !r.is_commitment) ?? [];
  return (
    <Card title="Looks regular">
      <p className="mb-3 text-xs text-muted">Found in your transactions by their timing and amounts. Confirm the ones that are real commitments.</p>
      {recurring.isPending ? <Loading /> : recurring.isError ? <ErrorNote error={recurring.error} /> :
        suggestions.length === 0 ? <EmptyState title="Nothing new found" /> : (
          <ul className="divide-y divide-line">{suggestions.map((r) => <DetectedRow key={r.key} r={r} />)}</ul>
        )}
    </Card>
  );
}

function DetectedRow({ r }: { r: Recurring }) {
  const confirm = useConfirmRecurring();
  const signed = r.direction === "debit" ? `-${r.typical_amount}` : r.typical_amount;
  return (
    <li className="py-2">
      <div className="flex justify-between gap-3 text-sm">
        <span className="min-w-0">
          <span className="font-medium">{r.name}</span>
          <span className="block text-xs text-muted">
            Looks like a payment {cadenceLabel(r.cadence)} · seen {r.occurrences} times · next about {shortDate(r.next_expected)}
          </span>
        </span>
        <Amount value={signed} className="shrink-0" />
      </div>
      {r.reasons.length > 0 && <p className="mt-1 text-xs text-muted">{r.reasons.join(" · ")}</p>}
      {r.may_have_stopped && <p className="text-xs text-warn-ink">It may have stopped: the last one was {shortDate(r.last)}.</p>}
      <div className="mt-1">
        <Button variant="secondary" onClick={() => confirm.mutate(r.key)} disabled={confirm.isPending}
          aria-label={`Confirm ${r.name} as a commitment`}>Yes, it's regular</Button>
      </div>
      {confirm.error && <ErrorNote error={confirm.error} />}
    </li>
  );
}

function CommitmentForm({ onDone }: { onDone: () => void }) {
  const [name, setName] = useState("");
  const [direction, setDirection] = useState<"debit" | "credit">("debit");
  const [amount, setAmount] = useState("");
  const [cadence, setCadence] = useState("monthly");
  const [nextDue, setNextDue] = useState(todayIso());
  const add = useAddCommitment();
  const minor = toMinor(amount);
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (minor === null) return;
    add.mutate({ name: name.trim(), direction, amount: fromMinor(minor), cadence, next_due: nextDue }, { onSuccess: onDone });
  };
  return (
    <form onSubmit={submit} className="flex flex-col gap-3">
      <fieldset className="flex flex-wrap gap-4 text-sm">
        <legend className="sr-only">Money in or out</legend>
        <label className="flex items-center gap-2"><input type="radio" name="commitment-direction" checked={direction === "debit"} onChange={() => setDirection("debit")} />I pay this</label>
        <label className="flex items-center gap-2"><input type="radio" name="commitment-direction" checked={direction === "credit"} onChange={() => setDirection("credit")} />I receive this</label>
      </fieldset>
      <div className="flex flex-wrap gap-3">
        <label className="flex min-w-40 flex-1 flex-col gap-1 text-sm font-medium">Name
          <input required maxLength={100} value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Rent" className={fieldClass} />
        </label>
        <label className="flex min-w-32 flex-1 flex-col gap-1 text-sm font-medium">Amount
          <input inputMode="decimal" required value={amount} onChange={(e) => setAmount(e.target.value)} placeholder="0.00"
            aria-invalid={amount !== "" && minor === null} className={`${fieldClass} tabular`} />
        </label>
      </div>
      <div className="flex flex-wrap gap-3">
        <label className="flex min-w-40 flex-1 flex-col gap-1 text-sm font-medium">How often
          <select value={cadence} onChange={(e) => setCadence(e.target.value)} className={fieldClass}>
            {Object.entries(CADENCE).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
          </select>
        </label>
        <label className="flex min-w-40 flex-1 flex-col gap-1 text-sm font-medium">Next due
          <input type="date" required value={nextDue} onChange={(e) => setNextDue(e.target.value)} className={fieldClass} />
        </label>
      </div>
      {add.error && <ErrorNote error={add.error} />}
      <div className="flex gap-2">
        <Button type="submit" disabled={!name.trim() || minor === null || minor === 0n || add.isPending}>{add.isPending ? "Saving…" : "Add commitment"}</Button>
        <Button type="button" variant="quiet" onClick={onDone}>Cancel</Button>
      </div>
      <p className="text-xs text-muted">Used for planning only. FinSight never pays anything.</p>
    </form>
  );
}
