import { type FormEvent, useState } from "react";
import { Navigate, useSearchParams } from "react-router";

import { useMe, useSignIn, useSignupOpen } from "../api/hooks";
import { Button, Card, ErrorNote } from "../components/ui";

export function SignIn() {
  const me = useMe();
  const signup = useSignupOpen();
  const [params] = useSearchParams();
  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const submit = useSignIn(mode);

  const next = params.get("next");
  const safeNext = next && next.startsWith("/") && !next.startsWith("//") ? next : "/"; // never an outside site
  if (me.data) return <Navigate to={safeNext} replace />;

  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    submit.mutate({ email, password });
  };

  return (
    <main className="flex min-h-screen items-center justify-center px-4">
      <div className="w-full max-w-sm">
        <h1 className="mb-1 text-center text-3xl font-semibold text-primary-ink">MoneyOS</h1>
        <p className="mb-6 text-center text-sm text-muted">Your money, in one calm place.</p>
        <Card>
          <h2 className="mb-4 text-lg font-semibold">{mode === "login" ? "Sign in" : "Create your account"}</h2>
          <form onSubmit={onSubmit} className="flex flex-col gap-4">
            <label className="flex flex-col gap-1 text-sm font-medium">
              Email
              <input type="email" required autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)}
                className="min-h-10 rounded-xl border border-field bg-surface px-3 text-base font-normal" />
            </label>
            <label className="flex flex-col gap-1 text-sm font-medium">
              Password
              <input type="password" required minLength={mode === "register" ? 10 : 1}
                autoComplete={mode === "login" ? "current-password" : "new-password"} value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="min-h-10 rounded-xl border border-field bg-surface px-3 text-base font-normal" />
              {mode === "register" && <span className="text-xs font-normal text-muted">At least 10 characters.</span>}
            </label>
            {submit.error && <ErrorNote error={submit.error} />}
            <Button type="submit" disabled={submit.isPending}>
              {submit.isPending ? "Please wait…" : mode === "login" ? "Sign in" : "Create account"}
            </Button>
          </form>
          {signup.data?.signup_open && (
            <p className="mt-4 text-center text-sm text-muted">
              {mode === "login" ? "New here? " : "Already have an account? "}
              <button type="button" className="font-medium text-primary-ink underline"
                onClick={() => { setMode(mode === "login" ? "register" : "login"); submit.reset(); }}>
                {mode === "login" ? "Create an account" : "Sign in"}
              </button>
            </p>
          )}
        </Card>
      </div>
    </main>
  );
}
