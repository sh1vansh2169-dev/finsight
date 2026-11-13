import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { PREVIEW } from "./fixtures";
import { fakeApi, HEALTH, ME, renderAt } from "./helpers";

const base = {
  "GET /auth/me": ME, "GET /health": HEALTH, "GET /categories": [], "GET /accounts": [],
  "GET /transactions": { total: 0, limit: 50, offset: 0, items: [] },
};

describe("statement inbox", () => {
  it("lists statements waiting for review and adds one only when asked", async () => {
    const staged = { ...PREVIEW.batch, id: 9, filename: "phonepe-march.pdf", created_at: "2026-11-13T10:00:00Z" };
    const calls = fakeApi({
      ...base,
      "GET /imports": [staged, { ...staged, id: 3, filename: "old.csv", status: "committed" }],
      "GET /imports/9": { ...PREVIEW, batch: staged },
      "POST /imports/9/commit": { ...staged, status: "committed", inserted_rows: 1 },
    });
    renderAt("/transactions");
    expect(await screen.findByText("1 statement(s) waiting for your review")).toBeInTheDocument();
    expect(screen.queryByText(/old\.csv/)).toBeNull(); // already added: not waiting
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Review phonepe-march.pdf" }));
    expect(await screen.findByText("Review a statement")).toBeInTheDocument();
    expect(calls.some((c) => c.path.includes("/commit"))).toBe(false); // opening it adds nothing
    await user.click(screen.getByRole("button", { name: "Add 1 transaction(s)" }));
    await waitFor(() => expect(calls.some((c) => c.method === "POST" && c.path === "/imports/9/commit")).toBe(true));
  });

  it("shows where the inbox folder is when it is on", async () => {
    fakeApi({ ...base, "GET /imports": [], "GET /imports/inbox": { enabled: true, folder: "C:\\Users\\you\\Downloads\\FinSight", note: null, waiting: [] } });
    renderAt("/transactions");
    await userEvent.setup().click(await screen.findByRole("button", { name: /Import statement/ }));
    expect(await screen.findByText("C:\\Users\\you\\Downloads\\FinSight")).toBeInTheDocument();
  });
});
