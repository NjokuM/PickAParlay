/**
 * Auth helpers — JWT token management + user state.
 *
 * Token is stored in localStorage. All API calls read it via getToken().
 * On 401, the user is redirected to /login.
 */

export interface AuthUser {
  user_id: number;
  username: string;
  display_name: string | null;
  is_admin: boolean;
}

const TOKEN_KEY = "pap_token";
const USER_KEY = "pap_user";

// ---------------------------------------------------------------------------
// Token management
// ---------------------------------------------------------------------------

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(TOKEN_KEY);
}

export function setAuth(token: string, user: AuthUser): void {
  localStorage.setItem(TOKEN_KEY, token);
  localStorage.setItem(USER_KEY, JSON.stringify(user));
}

export function clearAuth(): void {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(USER_KEY);
}

export function getUser(): AuthUser | null {
  if (typeof window === "undefined") return null;
  const raw = localStorage.getItem(USER_KEY);
  if (!raw) return null;
  try {
    return JSON.parse(raw) as AuthUser;
  } catch {
    return null;
  }
}

export function isLoggedIn(): boolean {
  return getToken() !== null;
}

export function isAdmin(): boolean {
  const user = getUser();
  return user?.is_admin === true;
}
