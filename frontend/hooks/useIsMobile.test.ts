import { describe, expect, it, vi } from "vitest";
import { act, renderHook } from "@testing-library/react";
import { useIsMobile } from "./useIsMobile";

describe("useIsMobile", () => {
  it("follows the media query", () => {
    let handler: ((e: { matches: boolean }) => void) | undefined;
    const remove = vi.fn();
    vi.spyOn(window, "matchMedia").mockImplementation(() => ({
      matches: true, addEventListener: (_: string, h: never) => { handler = h; }, removeEventListener: remove,
    }) as unknown as MediaQueryList);
    const { result, unmount } = renderHook(() => useIsMobile());
    expect(result.current).toBe(true);
    act(() => handler!({ matches: false }));
    expect(result.current).toBe(false);
    unmount();
    expect(remove).toHaveBeenCalled();
  });
});
