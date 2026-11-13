// Forms for Money Majra: people, groups, shared expenses, loans, repayments and
// cancelling an entry. Amounts are kept as the text the user typed and checked
// in whole paise (BigInt), so a split that "adds up" here adds up exactly.
import { type FormEvent, type ReactNode, useId, useState } from "react";

import { ApiError } from "../api/client";
import { useAddExpense, useAddLoan, useAddPayment, useAddPerson, useCreateGroup, useVoidEntry } from "../api/hooks";
import type { MajraEntry, MajraGroup, MajraPerson, SplitMethod } from "../api/types";
import { Button, ErrorNote, Notice } from "../components/ui";
import { fromMinor, money, toMinor, todayIso } from "../lib/format";

export const fieldClass = "min-h-10 w-full rounded-xl border border-field bg-surface px-3 text-sm font-normal";

export function personName(p: MajraPerson): string {
  return p.is_me ? "You" : p.name;
}

function Field({ label, hint, children }: { label: string; hint?: ReactNode; children: ReactNode }) {
  return (
    <label className="flex min-w-0 flex-1 flex-col gap-1 text-sm font-medium">
      {label}
      {children}
      {hint && <span className="text-xs font-normal text-muted">{hint}</span>}
    </label>
  );
}

function AmountInput({ value, onChange, label = "Amount" }: { value: string; onChange: (v: string) => void; label?: string }) {
  const invalid = value !== "" && toMinor(value) === null;
  return (
    <Field label={label} hint={invalid ? "Use a number with up to 2 decimals, like 1250.50" : undefined}>
      <input inputMode="decimal" autoComplete="off" required value={value} onChange={(e) => onChange(e.target.value)}
        aria-invalid={invalid} placeholder="0.00" className={`${fieldClass} tabular`} />
    </Field>
  );
}

function DateInput({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  return (
    <Field label="Date">
      <input type="date" required value={value} max={todayIso()} onChange={(e) => onChange(e.target.value)} className={fieldClass} />
    </Field>
  );
}

function FormActions({ pending, disabled, label, onCancel }: { pending: boolean; disabled?: boolean; label: string; onCancel: () => void }) {
  return (
    <div className="flex flex-wrap gap-2">
      <Button type="submit" disabled={pending || disabled}>{pending ? "Saving…" : label}</Button>
      <Button type="button" variant="quiet" onClick={onCancel}>Cancel</Button>
    </div>
  );
}

const amountText = (text: string) => fromMinor(toMinor(text) ?? 0n);

// ---------------------------------------------------------------- people, groups

export function AddPersonForm({ onDone }: { onDone: () => void }) {
  const [name, setName] = useState("");
  const add = useAddPerson();
  const submit = (e: FormEvent) => {
    e.preventDefault();
    add.mutate(name.trim(), { onSuccess: onDone });
  };
  return (
    <form onSubmit={submit} className="flex flex-col gap-3">
      <Field label="Name"><input required maxLength={100} value={name} onChange={(e) => setName(e.target.value)} className={fieldClass} /></Field>
      {add.error && <ErrorNote error={add.error} />}
      <FormActions pending={add.isPending} disabled={!name.trim()} label="Add person" onCancel={onDone} />
    </form>
  );
}

export function NewGroupForm({ people, onDone }: { people: MajraPerson[]; onDone: () => void }) {
  const others = people.filter((p) => !p.is_me);
  const [name, setName] = useState("");
  const [members, setMembers] = useState<number[]>([]);
  const create = useCreateGroup();
  const submit = (e: FormEvent) => {
    e.preventDefault();
    create.mutate({ name: name.trim(), member_ids: members }, { onSuccess: onDone });
  };
  if (others.length === 0) {
    return <Notice>Add the people you share costs with first.</Notice>;
  }
  return (
    <form onSubmit={submit} className="flex flex-col gap-3">
      <Field label="Group name"><input required maxLength={100} value={name} onChange={(e) => setName(e.target.value)}
        placeholder="e.g. Goa trip, Flat 4B" className={fieldClass} /></Field>
      <fieldset className="flex flex-col gap-1 text-sm">
        <legend className="mb-1 font-medium">Who is in it (you are always included)</legend>
        {others.map((p) => (
          <label key={p.id} className="flex items-center gap-2">
            <input type="checkbox" checked={members.includes(p.id)}
              onChange={(e) => setMembers((m) => (e.target.checked ? [...m, p.id] : m.filter((x) => x !== p.id)))} />
            {p.name}
          </label>
        ))}
      </fieldset>
      {create.error && <ErrorNote error={create.error} />}
      <FormActions pending={create.isPending} disabled={!name.trim() || members.length === 0} label="Create group" onCancel={onDone} />
    </form>
  );
}

// ---------------------------------------------------------------- loans

export function LoanForm({ people, onDone }: { people: MajraPerson[]; onDone: () => void }) {
  const others = people.filter((p) => !p.is_me);
  const [personId, setPersonId] = useState<number | "">(others[0]?.id ?? "");
  const [direction, setDirection] = useState<"lent" | "borrowed">("lent");
  const [amount, setAmount] = useState("");
  const [date, setDate] = useState(todayIso());
  const [description, setDescription] = useState("");
  const add = useAddLoan();
  if (others.length === 0) return <Notice>Add the person first.</Notice>;
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (personId === "") return;
    add.mutate({ person_id: personId, direction, amount: amountText(amount), date, description: description.trim() || (direction === "lent" ? "Lent" : "Borrowed") },
      { onSuccess: onDone });
  };
  return (
    <form onSubmit={submit} className="flex flex-col gap-3">
      <fieldset className="flex flex-wrap gap-4 text-sm">
        <legend className="sr-only">Direction</legend>
        <label className="flex items-center gap-2"><input type="radio" name="direction" checked={direction === "lent"} onChange={() => setDirection("lent")} />I lent money</label>
        <label className="flex items-center gap-2"><input type="radio" name="direction" checked={direction === "borrowed"} onChange={() => setDirection("borrowed")} />I borrowed money</label>
      </fieldset>
      <div className="flex flex-wrap gap-3">
        <Field label={direction === "lent" ? "To" : "From"}>
          <select value={personId} onChange={(e) => setPersonId(Number(e.target.value))} className={fieldClass}>
            {others.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
          </select>
        </Field>
        <AmountInput value={amount} onChange={setAmount} />
        <DateInput value={date} onChange={setDate} />
      </div>
      <Field label="What for (optional)"><input maxLength={200} value={description} onChange={(e) => setDescription(e.target.value)} className={fieldClass} /></Field>
      {add.error && <ErrorNote error={add.error} />}
      <FormActions pending={add.isPending} disabled={toMinor(amount) === null || toMinor(amount) === 0n} label="Save" onCancel={onDone} />
    </form>
  );
}

// ---------------------------------------------------------------- shared expenses

const METHODS: { value: SplitMethod; label: string }[] = [
  { value: "equal", label: "Equally" },
  { value: "exact", label: "By exact amounts" },
  { value: "percent", label: "By percentages" },
  { value: "shares", label: "By shares" },
];

/** Whether the per-person values add up, in exact units (paise, or hundredths of a percent). */
export function splitCheck(method: SplitMethod, total: string, values: string[]): { ok: boolean; message: string } {
  if (method === "equal") return { ok: values.length > 0, message: values.length > 0 ? `Split equally between ${values.length}.` : "Choose who shares it." };
  const parsed = values.map(toMinor);
  if (values.length === 0) return { ok: false, message: "Choose who shares it." };
  if (parsed.some((v) => v === null)) return { ok: false, message: "Each person needs a number with up to 2 decimals." };
  const sum = (parsed as bigint[]).reduce((a, b) => a + b, 0n);
  if (method === "shares") return { ok: sum > 0n, message: sum > 0n ? "Split in proportion to the shares." : "At least one share must be more than 0." };
  const target = method === "percent" ? 10000n : toMinor(total);
  if (target === null) return { ok: false, message: "Enter the total amount first." };
  const unit = (m: bigint) => (method === "percent" ? `${fromMinor(m)}%` : money(fromMinor(m)));
  if (sum === target) return { ok: true, message: `Adds up to ${unit(target)}.` };
  return { ok: false, message: `${unit(sum)} of ${unit(target)}: ${sum < target ? `${unit(target - sum)} left to assign` : `${unit(sum - target)} too much`}.` };
}

export function ExpenseForm({ group, onDone }: { group: MajraGroup; onDone: () => void }) {
  const me = group.members.find((m) => m.is_me);
  const [description, setDescription] = useState("");
  const [amount, setAmount] = useState("");
  const [date, setDate] = useState(todayIso());
  const [paidBy, setPaidBy] = useState<number>(me?.id ?? group.members[0]!.id);
  const [method, setMethod] = useState<SplitMethod>("equal");
  const [included, setIncluded] = useState<number[]>(group.members.map((m) => m.id));
  const [values, setValues] = useState<Record<number, string>>({});
  const add = useAddExpense();
  const id = useId();

  const chosen = group.members.filter((m) => included.includes(m.id));
  const check = splitCheck(method, amount, chosen.map((m) => values[m.id] ?? ""));
  const amountOk = toMinor(amount) !== null && toMinor(amount)! > 0n;

  const submit = (e: FormEvent) => {
    e.preventDefault();
    add.mutate({
      groupId: group.id, description: description.trim(), date, amount: amountText(amount), paid_by_id: paidBy,
      split: {
        method,
        participants: chosen.map((m) => (method === "equal" ? { person_id: m.id } : { person_id: m.id, value: fromMinor(toMinor(values[m.id] ?? "")!) })),
      },
    }, { onSuccess: onDone });
  };

  return (
    <form onSubmit={submit} className="flex flex-col gap-3">
      <Field label="What was it"><input required maxLength={200} value={description} onChange={(e) => setDescription(e.target.value)}
        placeholder="e.g. Dinner at the beach shack" className={fieldClass} /></Field>
      <div className="flex flex-wrap gap-3">
        <AmountInput value={amount} onChange={setAmount} label={`Total (${group.currency})`} />
        <DateInput value={date} onChange={setDate} />
        <Field label="Paid by">
          <select value={paidBy} onChange={(e) => setPaidBy(Number(e.target.value))} className={fieldClass}>
            {group.members.map((m) => <option key={m.id} value={m.id}>{personName(m)}</option>)}
          </select>
        </Field>
      </div>
      <Field label="Split">
        <select value={method} onChange={(e) => setMethod(e.target.value as SplitMethod)} className={fieldClass}>
          {METHODS.map((m) => <option key={m.value} value={m.value}>{m.label}</option>)}
        </select>
      </Field>
      <fieldset className="flex flex-col gap-2 text-sm" aria-describedby={`${id}-check`}>
        <legend className="mb-1 font-medium">Shared by</legend>
        {group.members.map((m) => {
          const on = included.includes(m.id);
          return (
            <div key={m.id} className="flex items-center gap-3">
              <label className="flex min-w-0 flex-1 items-center gap-2">
                <input type="checkbox" checked={on}
                  onChange={(e) => setIncluded((x) => (e.target.checked ? [...x, m.id] : x.filter((y) => y !== m.id)))} />
                {personName(m)}
              </label>
              {method !== "equal" && on && (
                <input inputMode="decimal" aria-label={`${personName(m)}: ${method === "exact" ? "amount" : method === "percent" ? "percentage" : "shares"}`}
                  value={values[m.id] ?? ""} onChange={(e) => setValues((v) => ({ ...v, [m.id]: e.target.value }))}
                  placeholder={method === "percent" ? "%" : method === "shares" ? "shares" : "0.00"} className={`${fieldClass} tabular max-w-32`} />
              )}
            </div>
          );
        })}
      </fieldset>
      <p id={`${id}-check`} className={`text-sm ${check.ok ? "text-muted" : "text-warn-ink"}`} aria-live="polite">{check.message}</p>
      {add.error && <ErrorNote error={add.error} />}
      <FormActions pending={add.isPending} disabled={!check.ok || !amountOk || !description.trim()} label="Add expense" onCancel={onDone} />
    </form>
  );
}

// ---------------------------------------------------------------- repayments

export interface PaymentDraft {
  payer_id: number;
  receiver_id: number;
  amount: string;
}

export function PaymentForm({ group, draft, onDone }: { group: MajraGroup; draft?: PaymentDraft; onDone: () => void }) {
  const me = group.members.find((m) => m.is_me)!;
  const other = group.members.find((m) => !m.is_me)!;
  const [payer, setPayer] = useState(draft?.payer_id ?? other.id);
  const [receiver, setReceiver] = useState(draft?.receiver_id ?? me.id);
  const [amount, setAmount] = useState(draft?.amount ?? "");
  const [date, setDate] = useState(todayIso());
  const [description, setDescription] = useState("Repayment");
  const add = useAddPayment();
  const looksRepeated = add.error instanceof ApiError && add.error.status === 409;

  const send = (confirm_duplicate: boolean) =>
    add.mutate({ groupId: group.id, payer_id: payer, receiver_id: receiver, amount: amountText(amount), date,
      description: description.trim() || "Repayment", confirm_duplicate }, { onSuccess: onDone });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    send(false);
  };
  const amountOk = toMinor(amount) !== null && toMinor(amount)! > 0n;

  return (
    <form onSubmit={submit} className="flex flex-col gap-3">
      <div className="flex flex-wrap gap-3">
        <Field label="Who paid">
          <select value={payer} onChange={(e) => { setPayer(Number(e.target.value)); add.reset(); }} className={fieldClass}>
            {group.members.map((m) => <option key={m.id} value={m.id}>{personName(m)}</option>)}
          </select>
        </Field>
        <Field label="Paid to">
          <select value={receiver} onChange={(e) => { setReceiver(Number(e.target.value)); add.reset(); }} className={fieldClass}>
            {group.members.map((m) => <option key={m.id} value={m.id}>{personName(m)}</option>)}
          </select>
        </Field>
      </div>
      <div className="flex flex-wrap gap-3">
        <AmountInput value={amount} onChange={(v) => { setAmount(v); add.reset(); }} />
        <DateInput value={date} onChange={(v) => { setDate(v); add.reset(); }} />
      </div>
      <Field label="Note"><input maxLength={200} value={description} onChange={(e) => setDescription(e.target.value)} className={fieldClass} /></Field>
      {payer === receiver && <p className="text-sm text-warn-ink">Who paid and who received must be different people.</p>}
      {looksRepeated ? (
        <div className="flex flex-col gap-2 rounded-xl bg-warn-bg p-3 text-sm text-warn-ink" role="alert">
          <p>A payment with the same people, amount and date is already recorded. Is this a second, separate payment?</p>
          <div className="flex flex-wrap gap-2">
            <Button type="button" onClick={() => send(true)} disabled={add.isPending}>Yes, it's a second payment</Button>
            <Button type="button" variant="secondary" onClick={onDone}>No, don't record it</Button>
          </div>
        </div>
      ) : (
        <>
          {add.error && <ErrorNote error={add.error} />}
          <FormActions pending={add.isPending} disabled={!amountOk || payer === receiver} label="Record payment" onCancel={onDone} />
        </>
      )}
      <p className="text-xs text-muted">This only records a payment that already happened. MoneyOS never sends money.</p>
    </form>
  );
}

// ---------------------------------------------------------------- cancelling

export function VoidEntry({ entry }: { entry: MajraEntry }) {
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState("");
  const cancel = useVoidEntry();
  if (!open) {
    return <button type="button" className="text-xs font-medium text-primary-ink underline" onClick={() => setOpen(true)}>Cancel entry</button>;
  }
  return (
    <form className="mt-2 flex w-full flex-wrap items-end gap-2"
      onSubmit={(e) => { e.preventDefault(); cancel.mutate({ id: entry.id, reason: reason.trim() }); }}>
      <Field label={`Why cancel "${entry.description}"?`} hint="It stays in the history, struck through.">
        <input required maxLength={200} value={reason} onChange={(e) => setReason(e.target.value)} className={fieldClass} />
      </Field>
      <Button type="submit" variant="danger" disabled={!reason.trim() || cancel.isPending}>{cancel.isPending ? "Cancelling…" : "Cancel entry"}</Button>
      <Button type="button" variant="quiet" onClick={() => setOpen(false)}>Keep it</Button>
      {cancel.error && <div className="w-full"><ErrorNote error={cancel.error} /></div>}
    </form>
  );
}
