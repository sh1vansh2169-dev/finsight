import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach, vi } from "vitest";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

// jsdom has no ResizeObserver or matchMedia; charts and the theme need them.
class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}
globalThis.ResizeObserver ??= ResizeObserverStub as unknown as typeof ResizeObserver;
window.matchMedia ??= ((query: string) => ({
  matches: false, media: query, onchange: null,
  addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {}, dispatchEvent: () => false,
})) as unknown as typeof window.matchMedia;

// Screens are loaded lazily. In tests each first load is compiled on the fly, and with
// several test files running in parallel that can exceed Testing Library's default
// 1 second wait, so findBy* waits up to 5 seconds. This changes timing only, not what is checked.
import { configure } from "@testing-library/react";
configure({ asyncUtilTimeout: 5000 });
