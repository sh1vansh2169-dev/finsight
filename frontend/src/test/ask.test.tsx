import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { fakeApi, HEALTH, ME, renderAt } from "./helpers";

const signedIn = { "GET /auth/me": ME, "GET /health": HEALTH };
const READY = { available: true, model: "qwen2.5:7b", message: "Ready" };

describe("ask", () => {
  it("explains how to set up the model when it is not available", async () => {
    fakeApi({ ...signedIn, "GET /assistant/status": { available: false, model: "qwen2.5:7b", message: "No model server at http://127.0.0.1:11434" } });
    renderAt("/insights/ask");
    expect(await screen.findByText("Set up the assistant")).toBeInTheDocument();
    expect(screen.getByText("ollama pull qwen2.5:7b")).toBeInTheDocument();
    expect(screen.getByText(/not sent anywhere else/)).toBeInTheDocument();
    expect(screen.queryByLabelText("Your question")).toBeNull();
  });

  it("shows answers, marks unverified figures and shows where figures came from", async () => {
    const calls = fakeApi({
      ...signedIn, "GET /assistant/status": READY,
      "POST /assistant/ask": {
        answer: "In March you spent ₹23,875.56. You saved about ₹70,000.",
        unverified_figures: ["₹70,000"],
        tool_calls: [{ name: "month_overview", arguments: { month: "2026-03" }, result: { spending_after_refunds: "23875.56" } }],
        stopped_early: false, model: "qwen2.5:7b",
      },
    });
    renderAt("/insights/ask");
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText("Your question"), "How did March go?");
    await user.click(screen.getByRole("button", { name: "Ask" }));

    expect(await screen.findByText(/In March you spent ₹23,875.56/)).toBeInTheDocument();
    expect(screen.getByText(/Not found in your MoneyOS data: ₹70,000/)).toBeInTheDocument();
    expect(screen.getByText("Where the figures came from (Month overview)")).toBeInTheDocument();
    expect(screen.getByText(/"spending_after_refunds": "23875.56"/)).toBeInTheDocument();
    const sent = calls.find((c) => c.path === "/assistant/ask")!;
    expect(sent.body).toEqual({ question: "How did March go?", history: [] });
    expect(sent.headers["X-MoneyOS-CSRF"]).toBe("1");
  });

  it("sends the conversation so far with a follow-up question", async () => {
    let n = 0;
    const calls = fakeApi({
      ...signedIn, "GET /assistant/status": READY,
      "POST /assistant/ask": () => ({ body: { answer: `Answer ${++n}`, unverified_figures: [], tool_calls: [], stopped_early: false, model: "m" } }),
    });
    renderAt("/insights/ask");
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Who owes me money?" }));
    expect(await screen.findByText("Answer 1")).toBeInTheDocument();
    expect(screen.getByText("No MoneyOS data was looked up for this answer.")).toBeInTheDocument();
    await user.type(screen.getByLabelText("Your question"), "And Ravi?");
    await user.click(screen.getByRole("button", { name: "Ask" }));
    await waitFor(() => expect(calls.filter((c) => c.path === "/assistant/ask")).toHaveLength(2));
    expect(calls.filter((c) => c.path === "/assistant/ask")[1]!.body).toEqual({
      question: "And Ravi?",
      history: [{ role: "user", content: "Who owes me money?" }, { role: "assistant", content: "Answer 1" }],
    });
  });

  it("shows why a question failed", async () => {
    fakeApi({
      ...signedIn, "GET /assistant/status": READY,
      "POST /assistant/ask": () => ({ status: 503, body: { detail: "No model server at http://127.0.0.1:11434" } }),
    });
    renderAt("/insights/ask");
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText("Your question"), "hi");
    await user.click(screen.getByRole("button", { name: "Ask" }));
    expect(await screen.findByText(/No model server/)).toBeInTheDocument();
  });
});
