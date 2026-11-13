import { type FormEvent, useState } from "react";

import { useDeleteAccount, useHealth, useMe, useSignOut } from "../api/hooks";
import { PageTitle } from "../components/AppShell";
import { Button, Card, ErrorNote } from "../components/ui";
import { type ThemeChoice, useTheme } from "../lib/theme";

export function Profile() {
  const me = useMe();
  const health = useHealth();
  const signOut = useSignOut();
  const [theme, setTheme] = useTheme();
  return (
    <>
      <PageTitle title="Profile" />
      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Account">
          <p className="text-sm">Signed in as <strong>{me.data?.email}</strong></p>
          <Button variant="secondary" className="mt-4" onClick={() => signOut.mutate()} disabled={signOut.isPending}>Sign out</Button>
        </Card>
        <Card title="Appearance">
          <fieldset className="flex flex-wrap gap-2">
            <legend className="sr-only">Theme</legend>
            {(["system", "light", "dark"] as ThemeChoice[]).map((choice) => (
              <label key={choice} className={`cursor-pointer rounded-xl border px-4 py-2 text-sm ${
                theme === choice ? "border-primary bg-primary-soft text-primary-ink" : "border-line"}`}>
                <input type="radio" name="theme" value={choice} checked={theme === choice} onChange={() => setTheme(choice)} className="sr-only" />
                {choice === "system" ? "Match my device" : choice === "light" ? "Light" : "Dark"}
              </label>
            ))}
          </fieldset>
        </Card>
      </div>
      <DeleteAccount />
      <p className="mt-6 text-xs text-muted">FinSight {health.data?.version}{health.data?.sample_data ? " · sample data" : ""}</p>
    </>
  );
}

function DeleteAccount() {
  const [open, setOpen] = useState(false);
  const [password, setPassword] = useState("");
  const [understood, setUnderstood] = useState(false);
  const remove = useDeleteAccount();
  const submit = (event: FormEvent) => {
    event.preventDefault();
    remove.mutate(password);
  };
  return (
    <Card title="Delete account" className="mt-4">
      <p className="text-sm text-ink-2">Permanently deletes your account and everything you stored: transactions, imports, budgets, Money Majra and commitments. This cannot be undone.</p>
      {!open ? (
        <Button variant="danger" className="mt-3" onClick={() => setOpen(true)}>Delete my account…</Button>
      ) : (
        <form onSubmit={submit} className="mt-3 flex flex-col gap-3">
          <label className="flex flex-col gap-1 text-sm font-medium">
            Your password
            <input type="password" required autoComplete="current-password" value={password}
              onChange={(e) => setPassword(e.target.value)} className="min-h-10 rounded-xl border border-field bg-surface px-3 font-normal" />
          </label>
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={understood} onChange={(e) => setUnderstood(e.target.checked)} />
            I understand everything will be deleted for good.
          </label>
          {remove.error && <ErrorNote error={remove.error} />}
          <div className="flex gap-2">
            <Button type="submit" variant="danger" disabled={!understood || !password || remove.isPending}>Delete everything</Button>
            <Button type="button" variant="quiet" onClick={() => { setOpen(false); setPassword(""); setUnderstood(false); }}>Cancel</Button>
          </div>
        </form>
      )}
    </Card>
  );
}
