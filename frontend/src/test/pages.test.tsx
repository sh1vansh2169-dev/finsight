import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { dashboard, PREVIEW, txn } from "./fixtures";
import { fakeApi, HEALTH, ME, renderAt } from "./helpers";

const signedIn = { "GET /auth/me": ME, "GET /health": HEALTH };

describe("sign-in", () => {
  it("sends signed-out visitors to sign in, then back where they were going", async () => {
    let me: object | null = null;
    const calls = fakeApi({
      "GET /auth/me": () => (me ? { body: me } : { status: 401, body: { detail: "not signed in" } }),
      "GET /auth/status": { signup_open: false },
      "GET /health": HEALTH,
      "POST /auth/login": () => { me = ME; return { body: { user: ME, token: null } }; },
      "GET /transactions": { total: 0, limit: 50, offset: 0, items: [] },
      "GET /categories": [], "GET /accounts": [],
    });
    const { router } = renderAt("/transactions");
    await screen.findByRole("heading", { name: "Sign in" });
    expect(router.state.location.search).toBe("?next=%2Ftransactions");
    expect(screen.queryByText("Create an account")).toBeNull(); // sign-up is closed

    const user = userEvent.setup();
    await user.type(screen.getByLabelText("Email"), "you@example.com");
    await user.type(screen.getByLabelText("Password"), "a-password");
    await user.click(screen.getByRole("button", { name: "Sign in" }));

    await screen.findByRole("heading", { name: "Transactions" });
    const login = calls.find((c) => c.path === "/auth/login")!;
    expect(login.body).toEqual({ email: "you@example.com", password: "a-password", use_cookie: true });
    expect(login.headers["X-MoneyOS-CSRF"]).toBe("1");
  });

  it("never redirects to another site after signing in", async () => {
    fakeApi({ ...signedIn, "GET /auth/status": { signup_open: false }, "GET /dashboard": dashboard() });
    const { router } = renderAt("/sign-in?next=//evil.example");
    await waitFor(() => expect(router.state.location.pathname).toBe("/"));
  });

  it("shows the server's reason when sign-in fails", async () => {
    fakeApi({
      "GET /auth/me": () => ({ status: 401, body: { detail: "not signed in" } }),
      "GET /auth/status": { signup_open: true },
      "POST /auth/login": () => ({ status: 401, body: { detail: "wrong email or password" } }),
    });
    renderAt("/sign-in");
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText("Email"), "you@example.com");
    await user.type(screen.getByLabelText("Password"), "nope");
    await user.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByText(/wrong email or password/)).toBeInTheDocument();
    expect(screen.getByText("Create an account")).toBeInTheDocument(); // sign-up is open
  });
});

describe("home", () => {
  it("shows the month's figures exactly and names transfers", async () => {
    fakeApi({ ...signedIn, "GET /dashboard": dashboard() });
    renderAt("/");
    await screen.findByRole("heading", { name: "October 2026" });
    expect(screen.getByText("₹85,000.00")).toBeInTheDocument();
    expect(screen.getByText("₹22,000.00")).toBeInTheDocument();
    expect(screen.getByText(/1 day\(s\) this month; they are shown as gaps, not as zero/)).toBeInTheDocument();
    const recent = screen.getByText("TRANSFER TO DEMO CARD").closest("li")!;
    expect(within(recent).getByText(/Between your accounts/)).toBeInTheDocument();
    expect(within(recent).queryByText(/Uncategorized/)).toBeNull();
  });

  it("invites an import when there is nothing yet", async () => {
    fakeApi({ ...signedIn, "GET /dashboard": dashboard({ currency: null, summary: null, recent_transactions: [] }) });
    renderAt("/");
    expect(await screen.findByText("No transactions yet")).toBeInTheDocument();
  });

  it("shows a sample-data banner when the database holds sample data", async () => {
    fakeApi({ ...signedIn, "GET /health": { ...HEALTH, data_mode: "sample", sample_data: true }, "GET /dashboard": dashboard() });
    renderAt("/");
    expect(await screen.findByText(/sample data/i)).toBeInTheDocument();
  });

  it("goes back to sign-in when the session expires", async () => {
    let expired = false;
    fakeApi({
      "GET /auth/me": () => (expired ? { status: 401, body: { detail: "session expired" } } : { body: ME }),
      "GET /health": HEALTH, "GET /auth/status": { signup_open: false },
      "GET /dashboard": () => { expired = true; return { status: 401, body: { detail: "session expired" } }; },
    });
    const { router } = renderAt("/");
    await waitFor(() => expect(router.state.location.pathname).toBe("/sign-in"));
  });
});

describe("transactions", () => {
  const page = (items = [txn()]) => ({ total: items.length, limit: 50, offset: 0, items });

  it("searches descriptions", async () => {
    const calls = fakeApi({
      ...signedIn, "GET /categories": ["Dining", "Housing", "Uncategorized"], "GET /accounts": [],
      "GET /transactions": (call) => ({ body: call.path.includes("q=") ? page([]) : page() }),
    });
    renderAt("/transactions");
    await screen.findByText("CHAI POINT KORAMANGALA");
    await userEvent.setup().type(screen.getByLabelText("Search descriptions"), "  rent ");
    expect(await screen.findByText("Nothing matches")).toBeInTheDocument();
    expect(calls.some((c) => c.path === "/transactions?q=rent&limit=50")).toBe(true);
  });

  it("saves only what was changed", async () => {
    const calls = fakeApi({
      ...signedIn, "GET /categories": ["Dining", "Housing", "Uncategorized"], "GET /accounts": [],
      "GET /transactions": page(),
      "PATCH /transactions/1": txn({ category: "Housing", category_basis: "user" }),
    });
    renderAt("/transactions");
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: /CHAI POINT KORAMANGALA/ }));
    const editor = within(screen.getByText(/Your changes are saved as yours/).parentElement!);
    const save = editor.getByRole("button", { name: "Save" });
    expect(save).toBeDisabled(); // nothing changed yet
    // A spending transaction can't be marked as income: the type list follows its direction.
    expect(editor.queryByRole("option", { name: "Income" })).toBeNull();
    expect(editor.getByRole("option", { name: "Lent" })).toBeInTheDocument();
    await user.selectOptions(editor.getByLabelText("Category"), "Housing");
    await user.click(save);
    await waitFor(() => expect(calls.find((c) => c.method === "PATCH")?.body).toEqual({ category: "Housing" }));
  });

  it("previews an import and adds it only when asked", async () => {
    const calls = fakeApi({
      ...signedIn, "GET /categories": [], "GET /accounts": [], "GET /transactions": page([]),
      "POST /imports/preview": PREVIEW,
      "POST /imports/7/commit": { ...PREVIEW.batch, status: "committed", inserted_rows: 1 },
    });
    renderAt("/transactions");
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: /Import statement/ }));
    const file = new File(["date,description,amount\n"], "october.csv", { type: "text/csv" });
    await user.upload(screen.getByLabelText(/Statement file/), file);
    // jsdom's "required" check can't see files attached by user.upload, so it blocks
    // the click silently; submit the form directly (a real browser submits normally).
    fireEvent.submit(screen.getByRole("button", { name: "Preview" }).closest("form")!);

    const summary = await screen.findByText((_, el) =>
      el?.tagName === "P" && el.textContent === "october.csv: 1 to add, 1 already recorded, 1 can't be read.");
    expect(summary).toBeInTheDocument();
    expect(screen.getByText("amount is not a number")).toBeInTheDocument();
    const form = calls.find((c) => c.path === "/imports/preview")!.body as FormData;
    expect((form.get("file") as File).name).toBe("october.csv");
    expect(form.get("day_first")).toBe("true");
    expect(calls.some((c) => c.path.includes("/commit"))).toBe(false); // nothing saved by previewing

    await user.click(screen.getByRole("button", { name: "Add 1 transaction(s)" }));
    expect(await screen.findByText("Added 1 transaction(s) from october.csv.")).toBeInTheDocument();
  });
});
