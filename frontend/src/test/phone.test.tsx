import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { fakeApi, HEALTH, ME, renderAt } from "./helpers";

const base = { "GET /auth/me": ME, "GET /health": HEALTH };
const PHONE = { id: 4, name: "Android phone", created_at: "2026-11-13T10:00:00Z", last_seen_at: null };

function nativeApp(permission: "granted" | "denied") {
  const plugin = {
    paired: false,
    status: vi.fn(async () => ({ paired: plugin.paired, permission, queued: 0, lastSentAt: null })),
    requestPermission: vi.fn(async () => ({ permission })),
    pair: vi.fn(async () => { plugin.paired = true; }),
    unpair: vi.fn(),
    importHistory: vi.fn(async () => ({ found: 12, sent: 12 })),
  };
  vi.stubGlobal("Capacitor", { isNativePlatform: () => true, Plugins: { FinSightSms: plugin } });
  return plugin;
}

describe("phone app", () => {
  it("in a browser, explains the app and lists connected phones", async () => {
    const calls = fakeApi({ ...base, "GET /phone/devices": [PHONE], "DELETE /phone/devices/4": () => ({ status: 204 }) });
    renderAt("/profile");
    expect(await screen.findByText(/OTPs and personal messages stay on the phone/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Connect this phone" })).toBeNull();
    await userEvent.setup().click(await screen.findByRole("button", { name: "Disconnect Android phone" }));
    await waitFor(() => expect(calls.some((c) => c.method === "DELETE" && c.path === "/phone/devices/4")).toBe(true));
  });

  it("inside the app, asks for SMS permission, then pairs this phone", async () => {
    const plugin = nativeApp("granted");
    const calls = fakeApi({ ...base, "GET /phone/devices": [], "POST /phone/devices": () => ({ status: 201, body: { ...PHONE, key: "fsp_secret" } }) });
    renderAt("/profile");
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Connect this phone" }));
    expect(await screen.findByText(/Connected\. New bank and UPI alerts/)).toBeInTheDocument();
    expect(plugin.requestPermission).toHaveBeenCalledBefore(plugin.pair);
    expect(plugin.pair).toHaveBeenCalledWith({ serverUrl: window.location.origin, key: "fsp_secret" });
    expect(calls.find((c) => c.path === "/phone/devices" && c.method === "POST")?.headers["X-MoneyOS-CSRF"]).toBe("1");
    await user.click(await screen.findByRole("button", { name: "Bring in the last 90 days" }));
    expect(await screen.findByText(/Found 12 transaction alert\(s\)/)).toBeInTheDocument();
    expect(plugin.importHistory).toHaveBeenCalledWith({ days: 90 });
  });

  it("does not pair when SMS permission is refused", async () => {
    const plugin = nativeApp("denied");
    const calls = fakeApi({ ...base, "GET /phone/devices": [] });
    renderAt("/profile");
    await userEvent.setup().click(await screen.findByRole("button", { name: "Connect this phone" }));
    expect(await screen.findByText(/SMS permission was not given/)).toBeInTheDocument();
    expect(plugin.pair).not.toHaveBeenCalled();
    expect(calls.some((c) => c.method === "POST" && c.path === "/phone/devices")).toBe(false); // no key made
  });
});
