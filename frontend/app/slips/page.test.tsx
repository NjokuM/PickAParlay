import { describe, expect, it, vi } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import SlipsPage from "./page";
import { viewport } from "@/vitest.setup";
import { calls, fail, makeSlip, mockBackend, renderWithProviders } from "@/test-utils";

const SLIPS = [makeSlip(2, { has_correlated_legs: true }), makeSlip(3), makeSlip(2)];

describe("SlipsPage", () => {
  it("builds best-value slips and filters them by leg count", async () => {
    const fetchMock = mockBackend({ "GET /api/bookmakers": ["fanduel"], "GET /api/slips": SLIPS });
    renderWithProviders(<SlipsPage />);
    expect(screen.getByText("Best Value")).toBeInTheDocument();
    await screen.findByRole("option", { name: "FanDuel" });
    await userEvent.click(screen.getByRole("button", { name: "Build Slips" }));
    expect(await screen.findByText("3 slips")).toBeInTheDocument();
    expect(calls(fetchMock)).toContain("GET /api/slips?min_score=50");
    expect(screen.getByText("⚠ correlated")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "3-Leg" }));
    expect(screen.getByText("1 slip")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "4-Leg" }));
    expect(screen.getByText("0 slips")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "All" }));
    expect(screen.getByText("3 slips")).toBeInTheDocument();
  });

  it("passes target odds, legs and book, expands detail, and saves", async () => {
    const fetchMock = mockBackend({
      "GET /api/bookmakers": ["fanduel"], "GET /api/slips": SLIPS,
      "POST /api/slips/save": { slip_id: 9, saved: true },
    });
    renderWithProviders(<SlipsPage />);
    await screen.findByRole("option", { name: "FanDuel" });
    const [legs, book] = screen.getAllByRole("combobox");
    await userEvent.selectOptions(legs, "2");
    await userEvent.selectOptions(book, "fanduel");
    await userEvent.type(screen.getByPlaceholderText("Any (Best Value)"), "4/1{Enter}");
    await screen.findByText("3 slips");
    expect(calls(fetchMock)).toContain("GET /api/slips?odds=4%2F1&legs=2&min_score=50&bookmaker=fanduel");
    await userEvent.click(screen.getAllByRole("button", { name: "View detail" })[1]);
    expect(screen.getByText(/Player 3 — OVER 12.5 Points/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Hide detail" }));
    expect(screen.queryByText(/Player 3 — OVER/)).toBeNull();
    await userEvent.click(screen.getAllByRole("button", { name: "Save Slip" })[1]);
    expect(await screen.findByRole("button", { name: "✓ Saved" })).toBeDisabled();
    const save = fetchMock.mock.calls.find(([u]) => String(u).endsWith("/api/slips/save"))!;
    expect(JSON.parse(String(save[1]?.body))).toEqual({ odds: "4/1", slip_index: 1, bookmaker: "fanduel", min_score: 50, legs: 2 });
  });

  it("alerts when saving fails", async () => {
    const alert = vi.spyOn(window, "alert").mockImplementation(() => {});
    mockBackend({ "GET /api/bookmakers": [], "GET /api/slips": SLIPS, "POST /api/slips/save": () => fail(500, "save failed") });
    renderWithProviders(<SlipsPage />);
    await userEvent.click(screen.getByRole("button", { name: "Build Slips" }));
    await screen.findByText("3 slips");
    await userEvent.click(screen.getAllByRole("button", { name: "Save Slip" })[0]);
    await waitFor(() => expect(alert).toHaveBeenCalledWith("save failed"));
  });

  it("explains a missing cache and shows other errors", async () => {
    mockBackend({ "GET /api/bookmakers": () => fail(500), "GET /api/slips": () => fail(503) });
    renderWithProviders(<SlipsPage />);
    expect(screen.getByText(/leave odds blank for best-value combos/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Build Slips" }));
    expect(await screen.findByText(/\/api\/slips.* → 503/)).toBeInTheDocument();
  });

  it("maps a 'no cached props' error to a hint", async () => {
    mockBackend({ "GET /api/bookmakers": [], "GET /api/slips": () => fail(404) });
    // get() errors read "API <path> → <status>"; simulate the backend message via a path containing "cached"
    renderWithProviders(<SlipsPage />);
    await userEvent.type(screen.getByPlaceholderText("Any (Best Value)"), "cached");
    await userEvent.click(screen.getByRole("button", { name: "Build Slips" }));
    expect(await screen.findByText("No cached props — go to Tonight and click ↻ Refresh first.")).toBeInTheDocument();
  });

  it("uses a compact layout on mobile", async () => {
    viewport.mobile = true;
    mockBackend({ "GET /api/bookmakers": [], "GET /api/slips": SLIPS });
    renderWithProviders(<SlipsPage />);
    await waitFor(() => expect(screen.queryByText("e.g. 4/1 · 5.0 · +400")).toBeNull());
    await userEvent.click(screen.getByRole("button", { name: "Build Slips" }));
    expect(await screen.findByText("3 slips")).toBeInTheDocument();
    expect(document.querySelectorAll("img").length).toBe(0);   // no headshots on mobile
  });
});
