import { describe, expect, it } from "vitest";
import { bookmakerLabel } from "./bookmakers";

describe("bookmakerLabel", () => {
  it("maps known keys to display names", () => {
    expect(bookmakerLabel("paddypower")).toBe("Paddy Power");
    expect(bookmakerLabel("betonlineag")).toBe("BetOnline");
  });
  it("falls back to the raw key", () => {
    expect(bookmakerLabel("newbook")).toBe("newbook");
  });
});
