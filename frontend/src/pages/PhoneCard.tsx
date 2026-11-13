import { useEffect, useState } from "react";

import { useDisconnectPhone, usePairPhone, usePhones } from "../api/more";
import { Button, Card, ErrorNote, Notice } from "../components/ui";
import { nativeSms, type SmsStatus } from "../lib/native";
import { shortDate } from "../lib/format";

/** The FinSight phone app: connect this phone (inside the app) and see or disconnect phones. */
export function PhoneCard() {
  const phones = usePhones();
  const disconnect = useDisconnectPhone();
  const sms = nativeSms();
  return (
    <Card title="Phone app" className="mt-4">
      {sms ? <ThisPhone /> : (
        <p className="text-sm text-ink-2">
          On Android, the FinSight app can bring in your bank and UPI SMS alerts by itself. Open FinSight in the
          app and connect the phone here. Only transaction alerts are sent; OTPs and personal messages stay on the phone.
        </p>
      )}
      {phones.data && phones.data.length > 0 && (
        <ul className="mt-4 divide-y divide-line">
          {phones.data.map((p) => (
            <li key={p.id} className="flex flex-wrap items-center justify-between gap-2 py-2 text-sm">
              <span>
                <span className="font-medium">{p.name}</span>
                <span className="block text-xs text-muted">
                  Connected {shortDate(p.created_at.slice(0, 10))}
                  {p.last_seen_at ? ` · last sent ${shortDate(p.last_seen_at.slice(0, 10))}` : " · nothing sent yet"}
                </span>
              </span>
              <Button variant="danger" onClick={() => disconnect.mutate(p.id)} disabled={disconnect.isPending}
                aria-label={`Disconnect ${p.name}`}>Disconnect</Button>
            </li>
          ))}
        </ul>
      )}
      {disconnect.error && <ErrorNote error={disconnect.error} />}
    </Card>
  );
}

function ThisPhone() {
  const sms = nativeSms()!;
  const pair = usePairPhone();
  const [status, setStatus] = useState<SmsStatus | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const refresh = () => sms.status().then(setStatus).catch(setError);
  useEffect(() => { void refresh(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const run = async (work: () => Promise<string | void>) => {
    setBusy(true);
    setError(null);
    try {
      const done = await work();
      if (done) setMessage(done);
      await refresh();
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  };

  const connect = () => run(async () => {
    const { permission } = await sms.requestPermission();
    if (permission !== "granted") return "SMS permission was not given, so nothing will be read. You can allow it later.";
    const paired = await pair.mutateAsync("Android phone");
    await sms.pair({ serverUrl: window.location.origin, key: paired.key });
    return "Connected. New bank and UPI alerts will appear under Transactions for you to review.";
  });
  const importPast = () => run(async () => {
    const { found, sent } = await sms.importHistory({ days: 90 });
    return `Found ${found} transaction alert(s) from the last 90 days; ${sent} sent for review.`;
  });

  if (!status) return <p className="text-sm text-muted">Checking this phone…</p>;
  return (
    <div className="flex flex-col gap-3">
      {status.paired ? (
        <p className="text-sm">
          This phone is connected. SMS permission: <strong>{status.permission}</strong>.
          {status.queued > 0 && ` ${status.queued} alert(s) waiting to be sent (they go when FinSight is reachable).`}
        </p>
      ) : (
        <p className="text-sm">
          Connect this phone to bring in bank and UPI SMS alerts automatically. FinSight will ask for permission to read
          SMS. It reads only messages that look like transaction alerts; OTPs and personal messages never leave the phone.
        </p>
      )}
      <div className="flex flex-wrap gap-2">
        {!status.paired && <Button onClick={connect} disabled={busy}>{busy ? "Connecting…" : "Connect this phone"}</Button>}
        {status.paired && status.permission !== "granted" && (
          <Button onClick={() => run(async () => { await sms.requestPermission(); })} disabled={busy}>Allow SMS</Button>
        )}
        {status.paired && status.permission === "granted" && (
          <Button variant="secondary" onClick={importPast} disabled={busy}>Bring in the last 90 days</Button>
        )}
      </div>
      {message && <Notice>{message}</Notice>}
      {error !== null && <ErrorNote error={error} />}
    </div>
  );
}
