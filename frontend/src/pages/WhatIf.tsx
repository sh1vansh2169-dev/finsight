import { type FormEvent, useState } from "react";

import { useCategories, useMajraPeople } from "../api/hooks";
import { useCommitments, useSimulation } from "../api/more";
import type { Cadence, Scenario, SimProjection } from "../api/types";
import { Amount, Button, Card, ErrorNote, Loading, Notice } from "../components/ui";
import { fromMinor, money, shortDate, signedMoney, toMinor } from "../lib/format";
import { fieldClass } from "./MajraForms";

const HORIZONS = [7, 30, 60, 90];

/** "2026-03-27" + 1 -> "2026-03-28" (calendar arithmetic in UTC, so no time-zone shifts). */
export function addDays(iso: string, days: number): string {
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(Date.UTC(y!, m! - 1, d! + days)).toISOString().slice(0, 10);
}

function describe(s: Scenario, currency: string): string {
  switch (s.kind) {
    case "purchase": return `Buy ${s.description} for ${money(s.amount, currency)} on ${shortDate(s.date)}`;
    case "new_recurring": return `${s.money_in ? "New income" : "New bill"}: ${s.name}, ${money(s.amount, currency)} ${s.cadence}, from ${shortDate(s.first_due)}`;
    case "reduce_category": return `Spend ${s.percent}% less on ${s.category}`;
    case "delay_repayment": return `${s.person} repays later than expected`;
    case "skip_commitment": return `Skip ${s.name}`;
  }
}

/** A deterministic projection of the next days, with changes the user tries out. */
export function WhatIf() {
  const [horizon, setHorizon] = useState(30);
  const [balanceText, setBalanceText] = useState("");
  const [scenarios, setScenarios] = useState<Scenario[]>([]);
  const balance = toMinor(balanceText);
  const sim = useSimulation({
    horizon_days: horizon,
    ...(balance !== null && { starting_balance: fromMinor(balance) }),
    scenarios,
  });
  const base = sim.data?.baseline;
  const currency = base?.currency ?? "INR";

  return (
    <div className="flex flex-col gap-4">
      <Card title="Set up">
        <div className="flex flex-wrap gap-3">
          <label className="flex min-w-40 flex-1 flex-col gap-1 text-sm font-medium">Look ahead
            <select value={horizon} onChange={(e) => setHorizon(Number(e.target.value))} className={fieldClass}>
              {HORIZONS.map((h) => <option key={h} value={h}>{h} days</option>)}
            </select>
          </label>
          <label className="flex min-w-40 flex-1 flex-col gap-1 text-sm font-medium">Money you have now (optional)
            <input inputMode="decimal" value={balanceText} onChange={(e) => setBalanceText(e.target.value)} placeholder="e.g. 45000"
              aria-invalid={balanceText !== "" && balance === null} className={`${fieldClass} tabular`} />
            <span className="text-xs font-normal text-muted">MoneyOS doesn't know your bank balance; without this it shows the change only.</span>
          </label>
        </div>
      </Card>

      <Card title="Try a change">
        {scenarios.length > 0 && (
          <ul className="mb-3 flex flex-col gap-2">
            {scenarios.map((s, i) => (
              <li key={i} className="flex items-center justify-between gap-3 rounded-xl bg-surface-2 px-3 py-2 text-sm">
                <span>{describe(s, currency)}</span>
                <Button variant="quiet" onClick={() => setScenarios((x) => x.filter((_, j) => j !== i))} aria-label={`Remove: ${describe(s, currency)}`}>Remove</Button>
              </li>
            ))}
          </ul>
        )}
        {scenarios.length < 10 && <ScenarioForm period={base && { first: addDays(base.start, 1), last: base.end }} onAdd={(s) => setScenarios((x) => [...x, s])} />}
      </Card>

      {sim.isPending ? <Loading label="Working it out" /> : (
        <>
          {sim.isError && <ErrorNote error={sim.error} />}
          {sim.data && <Result note={sim.data.note} base={sim.data.baseline} changed={sim.data.scenario} difference={sim.data.difference?.net_change} />}
        </>
      )}
    </div>
  );
}

function Range({ v, currency }: { v: { estimate: string; cautious: string | null; hopeful: string | null }; currency: string }) {
  return (
    <>
      <p className="tabular text-2xl font-semibold"><Amount value={v.estimate} currency={currency} /></p>
      <p className="text-xs text-muted">
        {v.cautious && v.hopeful
          ? `Likely between ${signedMoney(v.cautious, currency)} and ${signedMoney(v.hopeful, currency)}`
          : "Not enough history for a range"}
      </p>
    </>
  );
}

function Result({ note, base, changed, difference }: { note: string; base: SimProjection; changed?: SimProjection; difference?: string }) {
  const c = base.currency;
  const shown = changed ?? base;
  return (
    <Card title={`${shortDate(base.start)} to ${shortDate(base.end)} (estimate)`}>
      <div className={`grid gap-4 ${changed ? "sm:grid-cols-2" : ""}`}>
        <div>
          <p className="text-sm text-muted">{changed ? "As things are" : "Change over the period"}</p>
          <Range v={base.net_change} currency={c} />
          {base.balance && <p className="mt-1 text-sm">Ending with about <strong className="tabular">{money(base.balance.estimate, c)}</strong></p>}
        </div>
        {changed && (
          <div>
            <p className="text-sm text-muted">With your changes</p>
            <Range v={changed.net_change} currency={c} />
            {changed.balance && <p className="mt-1 text-sm">Ending with about <strong className="tabular">{money(changed.balance.estimate, c)}</strong></p>}
          </div>
        )}
      </div>
      {changed && difference && (
        <p className="mt-3 rounded-xl bg-surface-2 p-3 text-sm">
          Difference: <strong className="tabular">{signedMoney(difference, c)}</strong> over the period.
        </p>
      )}
      {shown.balance && shown.balance.cautious && shown.balance.cautious.startsWith("-") && (
        <div className="mt-3"><Notice tone="warn">On the cautious estimate, the money you have now would run out before {shortDate(shown.end)}.</Notice></div>
      )}
      <dl className="mt-4 grid gap-2 text-sm sm:grid-cols-3">
        <div><dt className="text-muted">Planned money in</dt><dd className="tabular">{money(shown.commitments.money_in, c)}</dd></div>
        <div><dt className="text-muted">Planned money out</dt><dd className="tabular">{money(shown.commitments.money_out, c)}</dd></div>
        <div><dt className="text-muted">Everyday spending</dt><dd className="tabular">{money(shown.everyday_spending.estimate, c)}</dd></div>
      </dl>
      {!/^0+(\.0+)?$/.test(shown.not_included.if_others_repay_you) && (
        <p className="mt-3 text-xs text-muted">Not counted: {money(shown.not_included.if_others_repay_you, c)} that others owe you. It may not arrive.</p>
      )}
      {changed && changed.changes.length > 0 && (
        <ul className="mt-3 list-disc pl-5 text-xs text-muted">{changed.changes.map((x) => <li key={x}>{x}</li>)}</ul>
      )}
      <details className="mt-3 text-sm">
        <summary className="cursor-pointer text-primary-ink">How this is worked out</summary>
        <ul className="mt-2 list-disc pl-5 text-xs text-muted">{shown.assumptions.map((a) => <li key={a}>{a}</li>)}</ul>
        <p className="mt-2 text-xs text-muted">{note}</p>
      </details>
    </Card>
  );
}

type Kind = Scenario["kind"];
const KINDS: { value: Kind; label: string }[] = [
  { value: "purchase", label: "A one-off purchase" },
  { value: "new_recurring", label: "A new bill or income" },
  { value: "reduce_category", label: "Spend less on a category" },
  { value: "skip_commitment", label: "Skip a commitment" },
  { value: "delay_repayment", label: "Someone repays later" },
];

function ScenarioForm({ period, onAdd }: { period?: { first: string; last: string }; onAdd: (s: Scenario) => void }) {
  const categories = useCategories();
  const commitments = useCommitments();
  const people = useMajraPeople();
  const [kind, setKind] = useState<Kind>("purchase");
  const [text, setText] = useState("");
  const [amount, setAmount] = useState("");
  const [date, setDate] = useState("");
  const [cadence, setCadence] = useState<Cadence>("monthly");
  const [moneyIn, setMoneyIn] = useState(false);
  const [percent, setPercent] = useState("20");
  // The projection covers the days after "as of"; a date outside it would change nothing.
  const day = date || period?.first || "";
  const minor = toMinor(amount);
  const pct = toMinor(percent);

  const build = (): Scenario | null => {
    switch (kind) {
      case "purchase": return minor && day ? { kind, amount: fromMinor(minor), date: day, description: text.trim() || "something" } : null;
      case "new_recurring": return minor && day && text.trim() ? { kind, name: text.trim(), amount: fromMinor(minor), cadence, first_due: day, money_in: moneyIn } : null;
      case "reduce_category": return text && pct && pct > 0n && pct <= 10000n ? { kind, category: text, percent: fromMinor(pct) } : null;
      case "skip_commitment": return text ? { kind, name: text } : null;
      case "delay_repayment": return text ? { kind, person: text } : null;
    }
  };
  const scenario = build();
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (!scenario) return;
    onAdd(scenario);
    setText(""); setAmount("");
  };

  const options = (list: string[]) => [<option key="" value="" disabled>Choose</option>, ...list.map((x) => <option key={x}>{x}</option>)];
  return (
    <form onSubmit={submit} className="flex flex-col gap-3">
      <label className="flex flex-col gap-1 text-sm font-medium">What to try
        <select value={kind} onChange={(e) => { setKind(e.target.value as Kind); setText(""); }} className={fieldClass}>
          {KINDS.map((k) => <option key={k.value} value={k.value}>{k.label}</option>)}
        </select>
      </label>
      <div className="flex flex-wrap gap-3">
        {(kind === "purchase" || kind === "new_recurring") && (
          <>
            <label className="flex min-w-40 flex-1 flex-col gap-1 text-sm font-medium">{kind === "purchase" ? "What (optional)" : "Name"}
              <input maxLength={100} value={text} onChange={(e) => setText(e.target.value)} className={fieldClass} />
            </label>
            <label className="flex min-w-32 flex-1 flex-col gap-1 text-sm font-medium">Amount
              <input inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value)} placeholder="0.00" className={`${fieldClass} tabular`} />
            </label>
            <label className="flex min-w-40 flex-1 flex-col gap-1 text-sm font-medium">{kind === "purchase" ? "Date" : "First due"}
              <input type="date" value={day} min={kind === "purchase" ? period?.first : undefined} max={period?.last}
                onChange={(e) => setDate(e.target.value)} className={fieldClass} />
            </label>
          </>
        )}
        {kind === "new_recurring" && (
          <>
            <label className="flex min-w-32 flex-1 flex-col gap-1 text-sm font-medium">How often
              <select value={cadence} onChange={(e) => setCadence(e.target.value as Cadence)} className={fieldClass}>
                {["weekly", "monthly", "quarterly", "yearly", "once"].map((x) => <option key={x}>{x}</option>)}
              </select>
            </label>
            <label className="flex items-center gap-2 self-end pb-2 text-sm"><input type="checkbox" checked={moneyIn} onChange={(e) => setMoneyIn(e.target.checked)} />It's income</label>
          </>
        )}
        {kind === "reduce_category" && (
          <>
            <label className="flex min-w-40 flex-1 flex-col gap-1 text-sm font-medium">Category
              <select value={text} onChange={(e) => setText(e.target.value)} className={fieldClass}>{options((categories.data ?? []).filter((c) => c !== "Uncategorized"))}</select>
            </label>
            <label className="flex min-w-32 flex-1 flex-col gap-1 text-sm font-medium">Less by (%)
              <input inputMode="decimal" value={percent} onChange={(e) => setPercent(e.target.value)} className={`${fieldClass} tabular`} />
            </label>
          </>
        )}
        {kind === "skip_commitment" && (
          <label className="flex min-w-40 flex-1 flex-col gap-1 text-sm font-medium">Commitment
            <select value={text} onChange={(e) => setText(e.target.value)} className={fieldClass}>
              {options((commitments.data ?? []).filter((c) => c.status === "active").map((c) => c.name))}
            </select>
          </label>
        )}
        {kind === "delay_repayment" && (
          <label className="flex min-w-40 flex-1 flex-col gap-1 text-sm font-medium">Person
            <select value={text} onChange={(e) => setText(e.target.value)} className={fieldClass}>
              {options((people.data ?? []).filter((p) => !p.is_me).map((p) => p.name))}
            </select>
          </label>
        )}
      </div>
      <div><Button type="submit" variant="secondary" disabled={!scenario}>Add this change</Button></div>
    </form>
  );
}
