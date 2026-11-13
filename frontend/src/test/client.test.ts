import { describe, expect, it } from "vitest";

import { ApiError, api, query } from "../api/client";
import { fakeApi } from "./helpers";

describe("api client", () => {
  it("adds the CSRF header to changes only", async () => {
    const calls = fakeApi({ "GET /things": [], "POST /things": { ok: true }, "PATCH /things/1": { ok: true } });
    await api("/things");
    await api("/things", { body: { a: 1 } });
    await api("/things/1", { method: "PATCH", body: { b: 2 } });
    expect(calls[0]!.headers["X-MoneyOS-CSRF"]).toBeUndefined();
    expect(calls[1]!.headers["X-MoneyOS-CSRF"]).toBe("1");
    expect(calls[2]!.headers["X-MoneyOS-CSRF"]).toBe("1");
    expect(calls[1]!.body).toEqual({ a: 1 });
  });

  it("turns error responses into readable errors", async () => {
    fakeApi({
      "GET /missing": () => ({ status: 404, body: { detail: "transaction 9 not found" } }),
      "POST /invalid": () => ({ status: 422, body: { detail: [{ msg: "Value error, use at least 10 characters" }] } }),
      "GET /broken": () => ({ status: 500, body: { detail: "Internal Server Error" } }),
    });
    await expect(api("/missing")).rejects.toEqual(new ApiError(404, "transaction 9 not found"));
    await expect(api("/invalid", { body: {} })).rejects.toThrow("use at least 10 characters");
    await expect(api("/broken")).rejects.toThrow("Internal Server Error");
  });

  it("handles no-content responses", async () => {
    fakeApi({ "POST /auth/logout": () => ({ status: 204 }) });
    await expect(api("/auth/logout", { method: "POST" })).resolves.toBeUndefined();
  });

  it("builds query strings without empty values", () => {
    expect(query({ q: "chai point", category: "", limit: 50, account: undefined })).toBe("?q=chai+point&limit=50");
    expect(query({})).toBe("");
  });
});
