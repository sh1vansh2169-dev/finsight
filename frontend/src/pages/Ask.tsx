import { type FormEvent, useState } from "react";

import { type AssistantAnswer, useAsk, useAssistantStatus } from "../api/more";
import { Button, Card, ErrorNote, Loading, Notice } from "../components/ui";
import { fieldClass } from "./MajraForms";

const TOOL_LABEL: Record<string, string> = {
  month_overview: "Month overview",
  find_transactions: "Transaction search",
  spending_between: "Totals between dates",
  upcoming_bills: "Upcoming bills",
  money_owed: "Money Majra balances",
  unusual_payments: "Unusual payments",
  what_if: "What-if estimate",
};

const EXAMPLES = [
  "How much did I spend on dining last month?",
  "What bills are due in the next two weeks?",
  "Who owes me money?",
  "What if I buy a 30000 laptop?",
];

interface Turn {
  question: string;
  reply?: AssistantAnswer;
}

/** Questions answered by a local model from MoneyOS's own figures. */
export function Ask() {
  const status = useAssistantStatus();
  const ask = useAsk();
  const [turns, setTurns] = useState<Turn[]>([]);
  const [question, setQuestion] = useState("");

  const send = (text: string) => {
    const q = text.trim();
    if (!q || ask.isPending) return;
    const history = turns.slice(-5).flatMap((t) => (t.reply
      ? [{ role: "user" as const, content: t.question }, { role: "assistant" as const, content: t.reply.answer }]
      : []));
    setTurns((all) => [...all, { question: q }]);
    setQuestion("");
    ask.mutate({ question: q, history }, {
      onSuccess: (reply) => setTurns((all) => all.map((t, i) => (i === all.length - 1 ? { ...t, reply } : t))),
      onError: () => setTurns((all) => all.slice(0, -1)),
    });
  };
  const submit = (e: FormEvent) => {
    e.preventDefault();
    send(question);
  };

  if (status.isPending) return <Loading label="Checking the assistant" />;
  if (status.isError) return <ErrorNote error={status.error} retry={() => status.refetch()} />;
  if (!status.data.available) {
    return (
      <Card title="Set up the assistant">
        <p className="text-sm">{status.data.message}</p>
        <ol className="mt-3 list-decimal space-y-1 pl-5 text-sm text-ink-2">
          <li>Install Ollama from ollama.com and start it.</li>
          <li>In a terminal, run <code className="rounded bg-surface-2 px-1">ollama pull {status.data.model}</code> (several GB).</li>
          <li>Come back here and <button type="button" className="font-medium text-primary-ink underline" onClick={() => status.refetch()}>check again</button>.</li>
        </ol>
        <p className="mt-3 text-xs text-muted">The model runs on this computer; your money data is not sent anywhere else.</p>
      </Card>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      <Notice>
        Answers come from your recorded data, looked up by MoneyOS. The assistant cannot change anything or move money,
        and it can still word things badly: check figures marked unverified. Model: {status.data.model}, on this computer.
      </Notice>

      {turns.length === 0 && (
        <div className="flex flex-wrap gap-2">
          {EXAMPLES.map((e) => (
            <button key={e} type="button" onClick={() => send(e)}
              className="rounded-full border border-line px-3 py-1.5 text-sm text-ink-2 hover:bg-surface-2">{e}</button>
          ))}
        </div>
      )}

      <ol className="flex flex-col gap-4" aria-live="polite">
        {turns.map((t, i) => (
          <li key={i} className="flex flex-col gap-2">
            <p className="self-end rounded-2xl bg-primary-soft px-4 py-2 text-sm text-primary-ink">{t.question}</p>
            {t.reply ? <Reply reply={t.reply} /> : <Loading label="Looking it up (a local model can take a minute)" />}
          </li>
        ))}
      </ol>

      {ask.error && <ErrorNote error={ask.error} />}
      <form onSubmit={submit} className="flex gap-2">
        <label className="sr-only" htmlFor="ask-question">Your question</label>
        <input id="ask-question" value={question} onChange={(e) => setQuestion(e.target.value)} maxLength={500}
          placeholder="Ask about your money" className={`${fieldClass} flex-1`} />
        <Button type="submit" disabled={!question.trim() || ask.isPending}>Ask</Button>
      </form>
    </div>
  );
}

function Reply({ reply }: { reply: AssistantAnswer }) {
  return (
    <div className="rounded-2xl border border-line bg-surface p-4 text-sm">
      <p className="whitespace-pre-wrap">{reply.answer}</p>
      {reply.unverified_figures.length > 0 && (
        <div className="mt-3"><Notice tone="warn">
          Not found in your MoneyOS data: {reply.unverified_figures.join(", ")}. The assistant may have worked these out
          itself or got them wrong; treat them as unverified.
        </Notice></div>
      )}
      {reply.tool_calls.length > 0 ? (
        <details className="mt-3">
          <summary className="cursor-pointer text-xs font-medium text-primary-ink">
            Where the figures came from ({reply.tool_calls.map((c) => TOOL_LABEL[c.name] ?? c.name).join(", ")})
          </summary>
          <ul className="mt-2 flex flex-col gap-2">
            {reply.tool_calls.map((c, i) => (
              <li key={i}>
                <p className="text-xs font-medium">{TOOL_LABEL[c.name] ?? c.name}</p>
                <pre className="mt-1 max-h-48 overflow-auto rounded-lg bg-surface-2 p-2 text-xs">{JSON.stringify(c.result, null, 2)}</pre>
              </li>
            ))}
          </ul>
        </details>
      ) : (
        <p className="mt-2 text-xs text-muted">No MoneyOS data was looked up for this answer.</p>
      )}
    </div>
  );
}
