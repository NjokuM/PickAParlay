import "@testing-library/jest-dom/vitest";
import { afterEach, vi } from "vitest";
import { cleanup } from "@testing-library/react";

// Pages can steer the stubbed router / viewport: `nav.pathname = "/login"`, `viewport.mobile = true`.
export const nav = { pathname: "/" };
export const viewport = { mobile: false };

afterEach(() => {
  cleanup();
  localStorage.clear();
  vi.clearAllMocks();
  nav.pathname = "/";
  viewport.mobile = false;
});

// Next.js app-router hooks — pages get a stub router; tests can inspect `routerPush`.
// The router object is stable across renders, as in Next (pages list it in effect deps).
export const routerPush = vi.fn();
const router = { push: routerPush, replace: routerPush, refresh: vi.fn(), back: vi.fn() };
vi.mock("next/navigation", () => ({
  useRouter: () => router,
  usePathname: () => nav.pathname,
  useSearchParams: () => new URLSearchParams(),
}));

// Browser APIs jsdom lacks (recharts / responsive layout)
class ResizeObserverStub { observe() {} unobserve() {} disconnect() {} }
(globalThis as unknown as { ResizeObserver: unknown }).ResizeObserver = ResizeObserverStub;
Object.defineProperty(window, "matchMedia", {
  writable: true,
  value: (query: string) => ({
    matches: viewport.mobile, media: query, onchange: null,
    addListener: () => {}, removeListener: () => {},
    addEventListener: () => {}, removeEventListener: () => {}, dispatchEvent: () => false,
  }),
});
