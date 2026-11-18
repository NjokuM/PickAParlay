import { describe, expect, it } from "vitest";
import { clearAuth, getToken, getUser, isAdmin, isLoggedIn, setAuth } from "./auth";

const user = { user_id: 1, username: "jane", display_name: "Jane", is_admin: true };

describe("auth storage", () => {
  it("stores and clears the token and user", () => {
    expect(isLoggedIn()).toBe(false);
    setAuth("tok", user);
    expect(getToken()).toBe("tok");
    expect(getUser()).toEqual(user);
    expect(isLoggedIn()).toBe(true);
    expect(isAdmin()).toBe(true);
    clearAuth();
    expect(getUser()).toBeNull();
    expect(isAdmin()).toBe(false);
  });
  it("ignores a corrupt stored user", () => {
    localStorage.setItem("pap_user", "{not json");
    expect(getUser()).toBeNull();
  });
});
