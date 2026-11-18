import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import LoginPage from "./page";
import { routerPush } from "@/vitest.setup";
import { getToken, getUser } from "@/lib/auth";
import { fail, mockBackend } from "@/test-utils";

const AUTH = { access_token: "jwt", user_id: 7, username: "mike", display_name: "Mike", is_admin: true };
const input = (sel: string) => document.querySelector(sel) as HTMLInputElement;
const submit = () => document.querySelector('button[type="submit"]') as HTMLButtonElement;

describe("LoginPage", () => {
  it("signs in, stores the session and goes home", async () => {
    const fetchMock = mockBackend({ "POST /api/auth/login": AUTH });
    render(<LoginPage />);
    await userEvent.type(input('input[autocomplete="username"]'), "mike");
    await userEvent.type(input('input[type="password"]'), "pw");
    await userEvent.click(submit());
    await screen.findByText("Sign In", { selector: "button[type=submit]" });
    expect(JSON.parse(String(fetchMock.mock.calls[0][1]?.body))).toEqual({ username: "mike", password: "pw" });
    expect(getToken()).toBe("jwt");
    expect(getUser()?.is_admin).toBe(true);
    expect(routerPush).toHaveBeenCalledWith("/");
  });

  it("registers with display name and invite code", async () => {
    const fetchMock = mockBackend({ "POST /api/auth/register": AUTH });
    render(<LoginPage />);
    await userEvent.click(screen.getAllByRole("button", { name: "Register" })[0]);
    await userEvent.type(input('input[autocomplete="username"]'), "mike");
    await userEvent.type(input('input[autocomplete="name"]'), "Mike N");
    await userEvent.type(input('input[type="password"]'), "pw");
    await userEvent.type(screen.getByPlaceholderText("Enter your invite code"), "CODE");
    await userEvent.click(screen.getByRole("button", { name: "Create Account" }));
    await screen.findByRole("button", { name: "Create Account" });
    expect(JSON.parse(String(fetchMock.mock.calls[0][1]?.body))).toEqual({
      username: "mike", password: "pw", display_name: "Mike N", invite_code: "CODE",
    });
    expect(routerPush).toHaveBeenCalledWith("/");
  });

  it("shows the API's error detail", async () => {
    mockBackend({ "POST /api/auth/login": () => fail(401, { detail: "Invalid username or password" }) });
    render(<LoginPage />);
    await userEvent.type(input('input[autocomplete="username"]'), "mike");
    await userEvent.type(input('input[type="password"]'), "bad");
    await userEvent.click(submit());
    expect(await screen.findByText("Invalid username or password")).toBeInTheDocument();
    expect(routerPush).not.toHaveBeenCalledWith("/");
  });

  it("shows a plain error when the body isn't JSON", async () => {
    mockBackend({ "POST /api/auth/login": () => fail(500, "boom") });
    render(<LoginPage />);
    await userEvent.type(input('input[autocomplete="username"]'), "mike");
    await userEvent.type(input('input[type="password"]'), "pw");
    await userEvent.click(submit());
    expect(await screen.findByText("boom")).toBeInTheDocument();
  });
});
