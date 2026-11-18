import { describe, expect, it } from "vitest";
import { fireEvent, render } from "@testing-library/react";
import { PlayerHeadshot } from "./PlayerHeadshot";

describe("PlayerHeadshot", () => {
  it("shows the NBA headshot and falls back on error", () => {
    const { container } = render(<PlayerHeadshot playerId={1628983} size={40} />);
    const img = container.querySelector("img")!;
    expect(img.getAttribute("src")).toContain("1628983");
    fireEvent.error(img);
    expect(container.querySelector("img")).toBeNull();
  });
  it("uses the placeholder without an id", () => {
    const { container } = render(<PlayerHeadshot playerId={null} />);
    expect(container.querySelector("img")).toBeNull();
  });
});
