import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import RootLayout from "./layout";
import { nav, routerPush, viewport } from "@/vitest.setup";
import { isLoggedIn } from "@/lib/auth";
import { loginAs, mockBackend } from "@/test-utils";

const ago = (mins: number) => new Date(Date.now() - mins * 60000).toISOString();
const credits = { used: 10, remaining: 490, total: 500, active_keys: 2, total_keys: 3 };
const schedule = (lastRefresh: string | null, jobs = [
  { id: "evening_refresh", next_run: "2026-11-19T18:00:00Z", next_run_human: "6pm" },
  { id: "grade_results", next_run: "2026-11-19T09:00:00Z", next_run_human: "9am" },
  { id: "idle", next_run: null, next_run_human: null },
]) => ({ jobs, last_refresh: lastRefresh, refresh_status: "done", last_grade: null });

const page = <RootLayout><p>page body</p></RootLayout>;

describe("RootLayout", () => {
  // <html>/<body> inside the test container makes React warn about nesting
  beforeEach(() => { vi.spyOn(console, "error").mockImplementation(() => {}); });

  it("renders the login page bare, without checking auth", () => {
    nav.pathname = "/login";
    const fetchMock = mockBackend({});
    render(page);
    expect(screen.getByText("page body")).toBeInTheDocument();
    expect(screen.queryByText("Tonight")).toBeNull();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("sends signed-out users to /login", () => {
    mockBackend({});
    render(page);
    expect(routerPush).toHaveBeenCalledWith("/login");
    expect(screen.queryByText("page body")).toBeNull();
  });

  it("shows the desktop sidebar with admin credits and schedule, and logs out", async () => {
    loginAs(true);
    mockBackend({ "GET /api/credits": credits, "GET /api/schedule": schedule(ago(5)) });
    nav.pathname = "/slips";
    render(page);
    expect(screen.getByText("page body")).toBeInTheDocument();
    for (const label of ["Tonight", "Slips", "Ladder", "History", "Results", "Analytics", "Grader"])
      expect(screen.getByText(label)).toBeInTheDocument();
    expect(await screen.findByText("10/500 used · 490 left")).toBeInTheDocument();
    expect(await screen.findByText("Refreshed: 5m ago")).toBeInTheDocument();
    expect(screen.getByText("Next: Grade @ 9am")).toBeInTheDocument();
    expect(screen.getByText("ADMIN")).toBeInTheDocument();
    await userEvent.click(screen.getByTitle("Sign out"));
    expect(isLoggedIn()).toBe(false);
    expect(routerPush).toHaveBeenCalledWith("/login");
  });

  it("hides admin panels from regular users and survives API errors", async () => {
    loginAs(false);
    const fetchMock = mockBackend({});   // every call 404s
    render(page);
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    expect(screen.getByText("Mike")).toBeInTheDocument();
    expect(screen.queryByText("ADMIN")).toBeNull();
    expect(screen.queryByText(/used ·/)).toBeNull();
  });

  it.each([
    [0, "just now"], [125, "2h 5m ago"], [60 * 50, "2d ago"],
  ])("labels a refresh %i minutes ago as %s", async (mins, label) => {
    loginAs(true);
    mockBackend({ "GET /api/credits": credits, "GET /api/schedule": schedule(ago(mins as number), []) });
    render(page);
    expect(await screen.findByText(`Refreshed: ${label}`)).toBeInTheDocument();
    expect(screen.queryByText(/^Next:/)).toBeNull();
  });

  it("uses a top bar, dropdown menu and bottom tabs on mobile", async () => {
    viewport.mobile = true;
    loginAs(true);
    mockBackend({
      "GET /api/credits": credits,
      "GET /api/schedule": schedule(ago(30), [{ id: "morning_refresh", next_run: "2026-11-19T06:20:00Z", next_run_human: "6:20am" }]),
    });
    render(page);
    expect(await screen.findByText("☰")).toBeInTheDocument();
    expect(screen.getByText("Tonight")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText("Mike")).toBeInTheDocument());
    await userEvent.click(screen.getByText("☰"));
    expect(await screen.findByText(/10\/500 used · 490 left \(2\/3 keys\)/)).toBeInTheDocument();
    expect(screen.getByText(/Refreshed: 30m ago/)).toBeInTheDocument();
    expect(screen.getByText(/Next: Refresh @ 6:20am/)).toBeInTheDocument();
    await userEvent.click(screen.getByText("✕"));
    expect(screen.queryByText("Sign Out")).toBeNull();
    await userEvent.click(screen.getByText("☰"));
    await userEvent.click(screen.getByText("Sign Out"));
    expect(routerPush).toHaveBeenCalledWith("/login");
  });

  it("falls back to the raw job id for unknown jobs", async () => {
    loginAs(true);
    mockBackend({ "GET /api/credits": credits,
      "GET /api/schedule": schedule(null, [{ id: "backfill", next_run: "2026-11-19T01:00:00Z", next_run_human: "1am" }]) });
    render(page);
    expect(await screen.findByText("Next: backfill @ 1am")).toBeInTheDocument();
  });
});
