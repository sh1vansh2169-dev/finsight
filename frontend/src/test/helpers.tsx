import { QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import { createMemoryRouter } from "react-router";
import { RouterProvider } from "react-router/dom";
import { vi } from "vitest";

import { makeQueryClient, routes } from "../App";

export interface Call {
  method: string;
  path: string;
  headers: Record<string, string>;
  body: unknown;
}

type Handler = (call: Call) => { status?: number; body?: unknown } | undefined;

/**
 * Replace fetch with a fake API. ``handlers`` maps "METHOD /path" (query
 * string excluded) to a response. Every call is recorded for assertions.
 */
export function fakeApi(handlers: Record<string, Handler | object>) {
  const calls: Call[] = [];
  vi.stubGlobal("fetch", vi.fn(async (input: string, init: RequestInit = {}) => {
    const url = new URL(input, "http://localhost");
    const method = (init.method ?? "GET").toUpperCase();
    const headers = Object.fromEntries(Object.entries((init.headers as Record<string, string>) ?? {}));
    let body: unknown = init.body;
    if (typeof init.body === "string") body = JSON.parse(init.body);
    const path = url.pathname.replace(/^\/api\/v1/, "");
    const call = { method, path: path + url.search, headers, body };
    calls.push(call);
    const key = `${method} ${path}`;
    const handler = handlers[key];
    const result = typeof handler === "function" ? (handler as Handler)(call) : handler ? { body: handler } : undefined;
    const status = result?.status ?? (handler === undefined ? 404 : 200);
    const payload = result?.body ?? (handler === undefined ? { detail: `no fake for ${key}` } : null);
    return new Response(status === 204 ? null : JSON.stringify(payload), { status });
  }));
  return calls;
}

export const ME = { id: 1, email: "you@example.com", created_at: "2026-11-01T00:00:00Z" };
export const HEALTH = { status: "ok", version: "0.9.0", data_mode: "real", sample_data: false };

export function renderAt(path: string) {
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  const client = makeQueryClient();
  const view = render(
    <QueryClientProvider client={client}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
  return { ...view, router, client };
}
